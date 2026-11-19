import asyncio

import pytest

from conflict_resolver.ai.advisor import Settings
from conflict_resolver.models import (
    ConflictContext,
    Task,
    FixedTask,
    Interval,
    Policy,
)
from conflict_resolver.planning import PlanningSession
from conflict_resolver.resolver import resolve
from conflict_resolver.scheduler import CoreScheduler, ReferenceScheduler


def make_context(duration=420):
    return ConflictContext(
        conflict_id="manual-test",
        schedule_version=0,
        target_task_id="task-1",
        tasks=[
            Task(
                id="task-1",
                name="Task kiểm tra",
                mandatory=False,
                importance=3,
                remaining_min=duration,
                earliest_start=480,
                deadline=900,
                chunk_min=20,
                chunk_max=400,
                allow_compress=True,
                allow_exclude=True,
            )
        ],
        active_windows=[
            Interval(
                start=480,
                end=880,
            )
        ],
    )


def test_compress_420_to_400():
    context = make_context()
    session = PlanningSession(context)

    report = asyncio.run(
        session.analyze(
            "task-1",
            Settings(ai_enabled=False),
        )
    )

    option = next(
        item
        for item in report.options
        if item.option_id == 2
    )

    assert option.is_available
    assert option.action_payload["new_duration"] == 400

    result = session.apply(
        "task-1",
        2,
        expected_version=0,
        duration=400,
    )

    assert result.status == "FEASIBLE"
    assert session.context.tasks[0].remaining_min == 400


def test_invalid_duration_keeps_old_context():
    context = make_context(100)

    context.tasks[0].chunk_min = 45
    context.tasks[0].chunk_max = 45

    context.active_windows = [
        Interval(start=480, end=570)
    ]

    session = PlanningSession(context)

    report = asyncio.run(
        session.analyze(
            "task-1",
            Settings(ai_enabled=False),
        )
    )

    option = next(
        item
        for item in report.options
        if item.option_id == 2
    )

    assert option.action_payload["new_duration"] == 90

    before = session.context.model_dump()

    # Chunk phải đúng 45 phút:
    # tổng 90 được nhưng tổng 89 không hợp lệ.
    with pytest.raises(ValueError):
        session.apply(
            "task-1",
            2,
            expected_version=0,
            duration=89,
        )

    assert session.context.model_dump() == before


def fixed(id, start, end, **kw):
    return FixedTask(
        id=id,
        name=id,
        interval=Interval(start=start, end=end),
        **kw,
    )


def option3(context, scheduler=None):
    report = asyncio.run(
        resolve(
            context,
            scheduler or CoreScheduler(),
            Settings(ai_enabled=False),
        )
    )

    return next(
        item
        for item in report.options
        if item.option_id == 3
    )


def mandatory_task(duration, deadline, **kw):
    values = dict(
        id="x",
        name="x",
        mandatory=True,
        importance=3,
        remaining_min=duration,
        earliest_start=0,
        deadline=deadline,
        chunk_min=30,
        chunk_max=duration,
    )
    values.update(kw)

    return Task(**values)


def test_option3_removes_marked_fixed_instead_of_shortening():
    # Cần 180 phút trước 12:00; "cafe" (8:00-10:00) được đánh dấu xóa được.
    # Fixed co dãn được nhưng KHÔNG được rút ngắn nữa.
    context = ConflictContext(
        conflict_id="remove",
        schedule_version=0,
        target_task_id="x",
        tasks=[mandatory_task(180, 720)],
        fixed_tasks=[
            fixed("cafe", 480, 600, can_remove=True, group="cafe"),
            fixed(
                "meeting", 600, 660,
                can_shorten=True, min_duration=15,
            ),
        ],
        active_windows=[Interval(start=480, end=720)],
    )

    for scheduler in (CoreScheduler(), ReferenceScheduler()):
        option = option3(context, scheduler)

        assert option.is_available

        changes = option.action_payload["changes"]

        assert [item["operation"] for item in changes] == [
            "REMOVE_FIXED"
        ]
        assert changes[0]["task_ids"] == ["cafe"]

    # Analyze không được sửa context gốc.
    assert len(context.fixed_tasks) == 2


def test_option3_never_removes_unmarked_fixed():
    context = ConflictContext(
        conflict_id="rigid",
        schedule_version=0,
        target_task_id="x",
        tasks=[mandatory_task(180, 720)],
        fixed_tasks=[
            fixed("cafe", 480, 600),
            fixed("meeting", 600, 660),
        ],
        active_windows=[Interval(start=480, end=720)],
    )

    assert not option3(context).is_available


def test_option3_only_removes_events_before_deadline():
    # "late" bắt đầu sau deadline nên không xóa được dù có cờ xóa.
    context = ConflictContext(
        conflict_id="late",
        schedule_version=0,
        target_task_id="x",
        tasks=[mandatory_task(180, 600)],
        fixed_tasks=[
            fixed("early", 480, 540),
            fixed("late", 600, 720, can_remove=True, group="late"),
        ],
        active_windows=[Interval(start=480, end=720)],
    )

    assert not option3(context).is_available


def test_option3_removes_prep_and_after_together():
    context = ConflictContext(
        conflict_id="group",
        schedule_version=0,
        target_task_id="x",
        tasks=[mandatory_task(150, 720)],
        fixed_tasks=[
            fixed("c.prep", 480, 510, can_remove=True,
                  group="c", ancillary=True),
            fixed("c.0", 510, 570, can_remove=True, group="c"),
            fixed("c.back", 570, 600, can_remove=True,
                  group="c", ancillary=True),
            fixed("block", 600, 660),
        ],
        active_windows=[Interval(start=480, end=720)],
    )

    option = option3(context)

    assert option.is_available

    change = option.action_payload["changes"][0]

    assert change["operation"] == "REMOVE_FIXED"
    assert sorted(change["task_ids"]) == ["c.0", "c.back", "c.prep"]
    assert change["removed_minutes"] == 120


def test_option3_widens_closest_to_deadline_first():
    # Deadline T3 21:00. Hai ngày kín lịch; T3 còn trống 20:00-21:00.
    # Cần 150 phút: T3 dậy sớm hơn 60 trước, phần còn lại mới nới T2.
    context = ConflictContext(
        conflict_id="order",
        schedule_version=0,
        target_task_id="x",
        tasks=[
            mandatory_task(
                150, 2700, chunk_min=15, chunk_max=150
            )
        ],
        fixed_tasks=[
            fixed("mon", 420, 1380),
            fixed("tue", 1860, 2640),
        ],
        active_windows=[
            Interval(start=420, end=1380),
            Interval(start=1860, end=2820),
        ],
        policy=Policy(
            max_earlier_minutes=60,
            max_later_minutes=60,
        ),
    )

    option = option3(context)

    assert option.is_available

    changes = option.action_payload["changes"]

    # Thay đổi đầu tiên luôn là ngày deadline (T3 = cửa sổ số 1).
    assert changes[0]["operation"] == "EXPAND_ACTIVE_WINDOW"
    assert changes[0]["window_index"] == 1
    assert changes[0]["earlier_minutes"] == 60
    assert changes[0]["later_minutes"] == 0

    # Ngày deadline không bao giờ thức quá deadline.
    assert changes[0]["new_end"] <= 2700 or changes[0]["later_minutes"] == 0

    # Phần còn lại mới đến T2, và chỉ khi T3 đã dùng hết mức cho phép.
    assert all(
        item["window_index"] == 0 for item in changes[1:]
    )
    assert sum(
        item["earlier_minutes"] + item["later_minutes"]
        for item in changes
    ) == 90


def test_apply_option3_removes_fixed_and_bumps_version():
    context = ConflictContext(
        conflict_id="apply",
        schedule_version=0,
        target_task_id="x",
        tasks=[mandatory_task(180, 720)],
        fixed_tasks=[
            fixed("cafe", 480, 600, can_remove=True, group="cafe"),
            fixed("meeting", 600, 660),
        ],
        active_windows=[Interval(start=480, end=720)],
    )

    session = PlanningSession(context)

    asyncio.run(
        session.analyze("x", Settings(ai_enabled=False))
    )

    result = session.apply("x", 3, expected_version=0)

    assert result.status == "FEASIBLE"
    assert session.context.schedule_version == 1
    assert [f.id for f in session.context.fixed_tasks] == ["meeting"]
