"""Input (cột "xóa được khi bận") -> snapshot -> context -> option 3."""
import asyncio
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src" / "input_module"))

from schedule_input.application.mapper import TaskFactory  # noqa: E402
from schedule_input.application.preview import SnapshotBuilder  # noqa: E402
from schedule_input.domain.models import (  # noqa: E402
    PlanningWindow,
    ScheduleInput,
)

from conflict_resolver.ai.advisor import Settings  # noqa: E402
from conflict_resolver.planning import (  # noqa: E402
    PlanningSession,
    context_from_snapshot,
)


def build_snapshot():
    # Tuần 19/10/2026, "bây giờ" = Thứ Hai 08:00.
    data = ScheduleInput(
        PlanningWindow(date(2026, 10, 19), datetime(2026, 10, 19, 8))
    )

    def fixed(**kw):
        row = dict(
            name="x", repeat="T2", start="08:00", end="10:00",
            is_flexible="Không",
        )
        row.update(kw)
        task, report = TaskFactory.from_raw(row, True)
        assert task is not None, report
        data.add(task)

    # Hai việc cố định T2 phủ gần hết 08:00-12:00; chỉ "Cà phê" xóa được.
    fixed(name="Cà phê", start="08:00", end="10:00",
          removable_when_busy="Có", prep_min=15)
    fixed(name="Họp", start="10:00", end="11:30")

    task, report = TaskFactory.from_raw(
        dict(
            name="Nộp báo cáo",
            mandatory="Có",
            importance=3,
            deadline="19/10/2026 12:00",
            remaining_min=150,
            focus="low",
            buffer_min=0,
            chunk_min=30,
            chunk_max=150,
        ),
        False,
    )
    assert task is not None, report
    data.add(task)

    return SnapshotBuilder().build(data)


def test_removable_flag_reaches_conflict_context():
    context = context_from_snapshot(build_snapshot())

    cafe = [f for f in context.fixed_tasks if f.name.startswith("Cà phê")]
    meeting = [f for f in context.fixed_tasks if f.name == "Họp"]

    # Sự kiện + thời gian chuẩn bị cùng nhóm, cùng được xóa.
    assert len(cafe) == 2
    assert all(f.can_remove for f in cafe)
    assert len({f.group for f in cafe}) == 1
    assert any(f.ancillary for f in cafe)

    assert meeting and not meeting[0].can_remove


def test_option3_end_to_end_removes_whole_occurrence():
    context = context_from_snapshot(build_snapshot())
    session = PlanningSession(context)

    baseline = session.plan()

    assert baseline.unscheduled  # chưa đủ chỗ: phải có conflict

    target = next(iter(baseline.unscheduled))

    report = asyncio.run(
        session.analyze(target, Settings(ai_enabled=False))
    )

    option = next(o for o in report.options if o.option_id == 3)

    assert option.is_available

    removes = [
        c for c in option.action_payload["changes"]
        if c["operation"] == "REMOVE_FIXED"
    ]

    assert len(removes) == 1
    assert removes[0]["name"] == "Cà phê"
    assert len(removes[0]["task_ids"]) == 2   # sự kiện + chuẩn bị

    session.apply(target, 3, report.schedule_version)

    assert not session.plan().unscheduled
    assert all(
        "Cà phê" not in f.name for f in session.context.fixed_tasks
    )
