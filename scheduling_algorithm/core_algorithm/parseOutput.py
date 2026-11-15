from __future__ import annotations

import json

from core_algorithm.models import MINUTES_PER_DAY, Config, FixedTask, SolveResult, Task


def free_time_by_day(result: SolveResult, cfg: Config, tasks: list[Task],
                     fixed: list[FixedTask]) -> list[list[tuple[int, int]]]:
    """Return sorted gaps in absolute minutes, indexed by day."""
    busy = [(item.start, item.end) for item in fixed]
    for task in tasks:
        chunks = result.chunks.get(task.id, [])
        if not chunks:
            continue
        break_slots = -cfg.to_slot(-task.break_minutes)
        buffer_slots = cfg.to_slot(task.buffer_minutes)
        last_end = max(end for _, end in chunks)
        for start, end in chunks:
            padding = max(break_slots, buffer_slots) if end == last_end else break_slots
            busy.append((cfg.to_minutes(start), cfg.to_minutes(end + padding)))
    busy.sort()

    days = []
    for day in range(cfg.num_days):
        base = day * MINUTES_PER_DAY
        cursor = max(cfg.now, base + cfg.day_start)
        day_end = base + cfg.day_end
        gaps = []
        for start, end in busy:
            if cursor >= day_end or start >= day_end:
                break
            if end <= cursor:
                continue
            if start > cursor:
                gaps.append((cursor, start))
            cursor = max(cursor, end)
        if cursor < day_end:
            gaps.append((cursor, day_end))
        days.append(gaps)
    return days


def parse_output(result: SolveResult, cfg: Config, tasks: list[Task],
                 fixed: list[FixedTask]) -> str:
    has_schedule = result.status in ("OPTIMAL", "FEASIBLE")
    data = {
        "status": result.status,
        "solve_time": result.solve_time,
        "unscheduled_task_ids": (
            [task.id for task in tasks if task.id not in result.chunks]
            if has_schedule
            else None
        ),
        "time_unit": "minutes",
        "time_origin": "day_0_00:00",
        "free_time": (
            [
                {
                    "day": day,
                    "gaps": [{"start": start, "end": end} for start, end in gaps],
                }
                for day, gaps in enumerate(free_time_by_day(result, cfg, tasks, fixed))
            ]
            if has_schedule
            else None
        ),
        "tasks": [
            {
                "task_id": task_id,
                "chunks": [
                    {
                        "start": cfg.to_minutes(start),
                        "end": cfg.to_minutes(end),
                    }
                    for start, end in pieces
                ],
            }
            for task_id, pieces in result.chunks.items()
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
