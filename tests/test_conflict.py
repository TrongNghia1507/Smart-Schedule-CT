import json
import unittest
from pathlib import Path

import httpx

from conflict_resolver.ai.advisor import Settings
from conflict_resolver.api import app
from conflict_resolver.models import ConflictContext, Interval
from conflict_resolver.resolver import resolve
from conflict_resolver.scheduler import ReferenceScheduler


def load_context():
    path = Path(__file__).parent / "fixtures" / "hard_conflict.json"

    return ConflictContext.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )


class ConflictTests(unittest.IsolatedAsyncioTestCase):
    async def test_hard_conflict_and_no_mutation(self):
        context = load_context()
        before = context.model_dump()

        report = await resolve(
            context,
            ReferenceScheduler(),
            Settings(ai_enabled=False),
        )

        options = {
            option.option_id: option
            for option in report.options
        }

        self.assertEqual(context.model_dump(), before)
        self.assertEqual(report.status, "CONFLICT")
        self.assertEqual(report.deficit_minutes, 60)

        self.assertTrue(options[1].is_available)
        self.assertTrue(options[2].is_available)
        self.assertFalse(options[3].is_available)
        self.assertTrue(options[4].is_available)

    async def test_soft_task_can_be_postponed(self):
        context = load_context()

        context.tasks[0].kind = "soft"
        context.tasks[0].max_postpone_minutes = 1440

        report = await resolve(
            context,
            ReferenceScheduler(),
            Settings(ai_enabled=False),
        )

        self.assertEqual(report.options[0].option_id, 3)
        self.assertTrue(report.options[0].is_available)

    async def test_fragmented_slots_are_not_enough(self):
        context = load_context()

        context.tasks[0].remaining_min = 60
        context.tasks[0].allow_compress = False
        context.tasks[0].allow_exclude = False

        context.fixed_tasks = []
        context.policy.max_later_minutes = 0

        context.active_windows = [
            Interval(start=480, end=500),
            Interval(start=510, end=530),
            Interval(start=540, end=560),
        ]

        report = await resolve(
            context,
            ReferenceScheduler(),
            Settings(ai_enabled=False),
        )

        self.assertEqual(report.status, "CONFLICT")
        self.assertFalse(
            any(option.is_available for option in report.options)
        )

    async def test_api(self):
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/conflicts/analyze",
                json=load_context().model_dump(),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["options"]), 4)