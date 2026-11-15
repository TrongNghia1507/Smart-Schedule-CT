"""Kiểm thử lớp validation khả năng hoàn thành + nối với conflict_resolver."""
from datetime import date, datetime
from dataclasses import replace

from schedule_input.application.mapper import TaskFactory
from schedule_input.application.services import TaskInputService
from schedule_input.domain.models import PlanningWindow, ScheduleInput, SleepWindow
from schedule_input.infrastructure.io import SampleDataProvider
from schedule_input.infrastructure.repositories import InMemoryRepository
from schedule_validation import (
    KindRule, ResolutionPolicy, apply_edits, check_feasibility_sync, option_to_edits,
)
from schedule_validation.edits import is_auto_applicable
from schedule_validation.model import build_week_model

MON = date(2026, 11, 16)


def week(now=datetime(2026, 11, 16, 8, 0), sleep=SleepWindow()):
    return ScheduleInput(PlanningWindow(MON, now, sleep))


def add(data, fixed=False, **raw):
    task, report = TaskFactory.from_raw(raw, fixed)
    assert task, report.issues
    data.add(task)
    return task


def deadline(data, name, when, minutes, kind="hard", importance=2, **kw):
    raw = dict(name=name, kind=kind, importance=importance, deadline=when,
               remaining_min=minutes, buffer_min=0, focus="low", chunk_min=30, chunk_max=120)
    raw.update(kw)
    return add(data, False, **raw)


def overloaded(kind="hard", importance=3, flexible=True):
    """Thứ Hai 08–18h chỉ trống 180 phút nhưng cần 300 phút."""
    d = week()
    add(d, True, name="Lớp co dãn", repeat="T2", start="09:00", end="12:00",
        is_flexible="Có" if flexible else "Không", min_duration_min=60)
    add(d, True, name="Lớp cứng", repeat="T2", start="13:00", end="17:00", is_flexible="Không")
    deadline(d, "Làm bài", "16/11/2026 18:00", 300, kind, importance)
    deadline(d, "Việc mềm khác", "20/11/2026 18:00", 60, "soft", 1)
    return d


def options_by_id(report):
    return {o.option_id: o for o in report.resolution.options}


# --- cân đối thời gian ------------------------------------------------------
def test_sample_data_is_feasible():
    report = check_feasibility_sync(SampleDataProvider().load())
    assert report.status == "OK" and not report.findings and report.resolution is None
    assert all(cp.deficit <= 0 for cp in report.checkpoints)


def test_conflict_detected_with_exact_numbers():
    report = check_feasibility_sync(overloaded())
    assert report.status == "CONFLICT"
    cp = next(c for c in report.checkpoints if c.conflict)
    assert (cp.demand, cp.free, cp.deficit) == (300, 180, 120)
    assert report.resolved.kind == "CAPACITY"
    assert report.resolution.status == "CONFLICT"


def test_equal_demand_and_free_is_not_conflict():
    d = overloaded()
    d.update(replace(d.deadline_tasks[0], remaining_min=180))
    assert check_feasibility_sync(d).status == "OK"


def test_buffer_counts_as_demand():
    d = overloaded()
    d.update(replace(d.deadline_tasks[0], remaining_min=180, buffer=type(d.deadline_tasks[0].buffer)(15)))
    report = check_feasibility_sync(d)
    assert report.status == "CONFLICT" and report.resolved.deficit == 15


def test_earliest_start_group_is_checked():
    # Mỗi nhóm đủ chỗ nếu tính từ bây giờ, nhưng nhóm bắt đầu muộn thì không.
    d = week(now=datetime(2026, 11, 16, 6, 0))
    deadline(d, "Việc sớm", "16/11/2026 12:00", 60)
    deadline(d, "Việc muộn", "16/11/2026 12:00", 200, earliest_start="16/11/2026 10:00")
    report = check_feasibility_sync(d)
    assert report.status == "CONFLICT"
    cp = next(c for c in report.checkpoints if c.conflict)
    assert cp.window_start == 600 and (cp.demand, cp.free) == (200, 120)


def test_resolver_only_called_when_time_is_short():
    from types import SimpleNamespace
    from schedule_validation import check_feasibility
    import asyncio

    class Spy:
        def __init__(self): self.calls = 0
        async def analyze(self, context):
            self.calls += 1
            return SimpleNamespace(status="CONFLICT")

    enough, short = Spy(), Spy()
    asyncio.run(check_feasibility(SampleDataProvider().load(), client=enough))
    asyncio.run(check_feasibility(overloaded(), client=short))
    assert enough.calls == 0 and short.calls == 1


def test_resolves_earliest_conflict_using_prefix_only():
    d = overloaded(kind="soft", importance=2)
    deadline(d, "Thứ Sáu quá tải", "20/11/2026 09:00", 6000, "hard", 3, chunk_max=600)  # xung đột muộn hơn
    report = check_feasibility_sync(d)
    assert report.resolved.deadline == 1080  # Thứ Hai 18:00
    # Option cho mốc sớm vẫn kiểm chứng được dù mốc muộn còn thiếu.
    assert any(o.is_available for o in report.resolution.options)
    assert len([f for f in report.findings if f.kind == "CAPACITY"]) >= 2


# --- option phải đúng ngữ cảnh ---------------------------------------------
def test_all_option_types_offered_to_user_on_conflict():
    # Người dùng chọn lúc xung đột: không loại sẵn option nào theo "kind".
    for kind in ("hard", "asap", "soft"):
        opts = options_by_id(check_feasibility_sync(overloaded(kind, 3)))
        assert opts[1].is_available and opts[2].is_available and opts[4].is_available, kind
    # Task hard không tự dời hạn; option 3 dời task soft importance thấp hơn
    # nằm TRONG phần lịch đang xét (task soft hạn Thứ Sáu không giúp được mốc Thứ Hai).
    d = week()
    add(d, True, name="Lớp cứng", repeat="T2", start="09:00", end="17:00", is_flexible="Không")
    deadline(d, "Làm bài", "16/11/2026 18:00", 100, "hard", 3)
    deadline(d, "Việc mềm", "16/11/2026 18:00", 30, "soft", 1)
    report = check_feasibility_sync(d)
    opt = options_by_id(report)[3]
    assert opt.is_available and opt.action_payload["operation"] == "POSTPONE_TASK"
    assert d.get_by_id(opt.action_payload["task_id"]).name == "Việc mềm"
    far = options_by_id(check_feasibility_sync(overloaded("hard", 3)))[3]
    assert not far.is_available and "soft" in far.unavailable_reason


def test_option_unavailable_when_context_forbids_it():
    # Hard, không còn task soft nào thấp hơn để dời -> option 3 báo lý do cụ thể.
    d = overloaded("hard", 3)
    d.remove(d.deadline_tasks[1].id)
    opt = options_by_id(check_feasibility_sync(d))[3]
    assert not opt.is_available and "soft" in opt.unavailable_reason and "Làm bài" in opt.unavailable_reason
    # Cấm cứng một loại phương án qua policy -> lý do nêu rõ.
    no_exclude = ResolutionPolicy(rules={k: KindRule(True, False, True, 0.0) for k in ("soft", "asap", "hard")})
    opt = options_by_id(check_feasibility_sync(overloaded("soft", 2), policy=no_exclude))[1]
    assert not opt.is_available and "allow_exclude" in opt.unavailable_reason


def test_soft_task_gets_exclude_compress_postpone():
    opts = options_by_id(check_feasibility_sync(overloaded("soft", 2)))
    assert opts[1].is_available and opts[2].is_available and opts[3].is_available
    assert opts[2].action_payload["new_duration"] == 180


def test_relax_unavailable_without_flexible_fixed():
    report = check_feasibility_sync(
        overloaded("soft", 2, flexible=False),
        policy=ResolutionPolicy(max_earlier_minutes=0, max_later_minutes=0),
    )
    opt = options_by_id(report)[4]
    assert not opt.is_available and "không có việc cố định" in opt.unavailable_reason.lower()


def test_relax_not_offered_for_importance_one_target():
    # Fixed co dãn có importance 1; target importance 1 không được phép đè lên nó.
    report = check_feasibility_sync(
        overloaded("asap", 1),
        policy=ResolutionPolicy(max_earlier_minutes=0, max_later_minutes=0),
    )
    assert not options_by_id(report)[4].is_available


def test_window_expansion_is_manual_not_auto():
    # Thiếu 20 phút, không có việc cố định co dãn: chỉ còn cách mượn giờ ngủ.
    d = week(now=datetime(2026, 11, 16, 8, 0))
    deadline(d, "Việc gấp tối", "16/11/2026 23:30", 920, "hard", 3, chunk_max=600)
    report = check_feasibility_sync(d)
    assert report.status == "CONFLICT" and report.resolved.deficit == 20
    relax = options_by_id(report)[4]
    assert relax.is_available
    edits = option_to_edits(relax, report.model, d)
    assert any(not e.auto for e in edits) and not is_auto_applicable(edits)
    assert "giờ ngủ" in " ".join(e.description for e in edits)
    # Tắt chính sách mượn giờ ngủ thì option phải báo không khả dụng, có lý do.
    off = check_feasibility_sync(d, policy=ResolutionPolicy(max_earlier_minutes=0, max_later_minutes=0))
    assert not options_by_id(off)[4].is_available


def test_compress_floor_respects_policy_ratio():
    rule = KindRule(True, True, True, min_keep_ratio=0.9)
    policy = ResolutionPolicy(rules={"soft": rule, "asap": rule, "hard": rule})
    opts = options_by_id(check_feasibility_sync(overloaded("soft", 2), policy=policy))
    # Sàn 270 phút vẫn không đủ 180 trống -> bị loại, kèm lý do đã kiểm chứng.
    assert not opts[2].is_available and "kiểm chứng" in opts[2].unavailable_reason


# --- áp dụng lại vào input module -------------------------------------------
def service_for(data):
    return TaskInputService(data, InMemoryRepository(), now_override=data.window.now)


def test_apply_compress_then_revalidate_ok_and_undo():
    d = overloaded("soft", 2)
    service = service_for(d)
    report = check_feasibility_sync(service.data)
    option = options_by_id(report)[2]
    result = apply_edits(service, option_to_edits(option, report.model, service.data))
    assert not result.has_errors()
    assert check_feasibility_sync(service.data).status == "OK"
    service.undo()
    assert check_feasibility_sync(service.data).status == "CONFLICT"


def test_apply_postpone_and_shorten_fixed_and_exclude():
    for option_id in (3, 1, 4):
        d = overloaded("soft", 2)
        service = service_for(d)
        report = check_feasibility_sync(service.data)
        option = options_by_id(report)[option_id]
        assert option.is_available
        result = apply_edits(service, option_to_edits(option, report.model, service.data))
        assert not result.has_errors(), result.issues
        assert check_feasibility_sync(service.data).status == "OK", option_id


def test_apply_refuses_manual_option():
    d = overloaded()
    service = service_for(d)
    from schedule_validation.edits import InputEdit
    result = apply_edits(service, [InputEdit("MANUAL", None, description="x")])
    assert result.has_errors() and service.data is d


# --- biên và độ bền ---------------------------------------------------------
def test_deadline_after_week_is_clamped_or_skipped():
    d = week()
    deadline(d, "Hạn tuần sau", "25/11/2026 12:00", 60)
    assert build_week_model(d).tasks[0].deadline == 10080
    skip = build_week_model(d, ResolutionPolicy(out_of_week_deadline="skip"))
    assert not skip.tasks and skip.skipped[0].code == "AFTER_WEEK"


def test_week_already_over_and_sleep_everything():
    over = week(now=datetime(2026, 11, 30, 8, 0))
    deadline(over, "x", "30/11/2026 12:00", 30)
    assert check_feasibility_sync(over).status == "NOT_CHECKED"
    asleep = week(sleep=SleepWindow(0, 1440))
    deadline(asleep, "x", "17/11/2026 12:00", 30)
    assert check_feasibility_sync(asleep).status == "NOT_CHECKED"


def test_many_fixed_occurrences_are_merged_under_limit():
    d = week(now=datetime(2026, 11, 16, 0, 0))
    for i in range(40):  # 40 việc lặp x 7 ngày = 280 > giới hạn 200 của ConflictContext
        add(d, True, name=f"Cố định {i}", repeat="T2->CN", start="09:00", end="09:10", is_flexible="Không")
    deadline(d, "Việc", "22/11/2026 12:00", 60)
    assert check_feasibility_sync(d).resolver_error is None


def test_resolver_failure_does_not_crash():
    class Broken:
        async def analyze(self, context):
            raise RuntimeError("down")
    from schedule_validation import check_feasibility
    import asyncio
    report = asyncio.run(check_feasibility(overloaded(), client=Broken()))
    assert report.status == "CONFLICT" and "down" in report.resolver_error
