"""Input (cột "xóa được khi bận") -> snapshot -> context -> option 3."""
import asyncio
from datetime import date, datetime

from schedule_input.application.mapper import TaskFactory
from schedule_input.application.preview import SnapshotBuilder
from schedule_input.domain.models import (
    PlanningWindow,
    ScheduleInput,
)

from conflict_resolver.ai.advisor import Settings
from conflict_resolver.calendar_view import (
    BLOCK_COLORS,
    Block,
    calendar_events,
    deadline_styles,
    option_preview_html,
    schedule_blocks,
)
from conflict_resolver.planning import (
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
    blocks = schedule_blocks(option.full_schedule, option.active_windows)
    week = date(2026, 10, 19)
    styles = deadline_styles([{"id": target, "importance": 3}])
    preview = option_preview_html("Phương án 3", week, blocks, styles, {}, "vi")
    assert "③ Nộp báo cáo" in preview and "Cà phê" not in preview
    assert styles[target][1] in preview
    shades = []
    for level, mark in enumerate("①②③", 1):
        styles = deadline_styles([{"id": target, "importance": level}])
        events = calendar_events(week, blocks, styles, {})
        deadline = next(event for event in events if "deadline-band" in event["classNames"])
        assert deadline["backgroundColor"] == styles[target][1]
        assert deadline["title"].startswith(mark)
        assert deadline["start"].startswith("2026-10-19T")
        shades.append(deadline["backgroundColor"])
    for index in (1, 3, 5):
        light, medium, dark = (int(shade[index:index + 2], 16) for shade in shades)
        assert light > medium > dark

    session.apply(target, 3, report.schedule_version)

    assert not session.plan().unscheduled
    assert all(
        "Cà phê" not in f.name for f in session.context.fixed_tasks
    )


def test_calendar_preserves_fixed_colors_and_distinguishes_tasks_at_same_importance():
    styles = deadline_styles([{"id": "a", "importance": 2}, {"id": "b", "importance": 2}])
    blocks = [
        Block(480, 510, "A (1/2)", "deadline", "a"),
        Block(530, 560, "A (2/2)", "deadline", "a"),
        Block(560, 600, "B", "deadline", "b"),
        Block(600, 660, "Custom", "fixed", "F2@0.0"),
        Block(660, 720, "Default", "fixed", "F3@0.0"),
    ]
    events = calendar_events(date(2026, 10, 19), blocks, styles, {"F2": "#409c92"})
    first, second, other, custom, default = events
    assert first["backgroundColor"] == second["backgroundColor"] != other["backgroundColor"]
    assert all(event["title"].startswith("② ") for event in (first, second, other))
    assert custom["backgroundColor"] == "#409c92"
    assert default["backgroundColor"] == BLOCK_COLORS["fixed"][0]
