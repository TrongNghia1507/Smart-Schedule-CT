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
from conflict_resolver.scheduler import CoreScheduler


def make_context(duration=420):
    return ConflictContext(
        conflict_id="manual-test",
        schedule_version=0,
        target_task_id="task-1",
        tasks=[
            Task(
                id="task-1",
                name="Task kiểm tra",
                kind="soft",
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


def test_relax_fixed_then_two_days():
    context = make_context(140)

    context.tasks[0].deadline = 2160
    context.tasks[0].chunk_min = 10
    context.tasks[0].chunk_max = 100

    context.active_windows = [
        Interval(start=480, end=540),
        Interval(start=1920, end=1980),
    ]

    context.policy = Policy(
        max_later_minutes=15
    )

    context.fixed_tasks = [
        FixedTask(
            id="fixed-1",
            name="Fixed linh hoạt",
            interval=Interval(
                start=480,
                end=510,
            ),
            can_shorten=True,
            min_duration=10,
        )
    ]

    report = asyncio.run(
        resolve(
            context,
            CoreScheduler(),
            Settings(ai_enabled=False),
        )
    )

    option = next(
        item
        for item in report.options
        if item.option_id == 4
    )

    assert option.is_available

    operations = [
        change["operation"]
        for change in option.action_payload["changes"]
    ]

    assert operations == [
        "SHORTEN_FIXED",
        "EXPAND_ACTIVE_WINDOW",
        "EXPAND_ACTIVE_WINDOW",
    ]

    # Analyze không được sửa context gốc.
    assert context.fixed_tasks[0].interval.end == 510