from __future__ import annotations

import json

from models import Config, SolveResult, Task


def parse_output(result: SolveResult, cfg: Config, tasks: list[Task]) -> str:
    data = {
        "status": result.status,
        "solve_time": result.solve_time,
        "unscheduled_task_ids": (
            [task.id for task in tasks if task.id not in result.chunks]
            if result.status in ("OPTIMAL", "FEASIBLE")
            else None
        ),
        "time_unit": "minutes",
        "time_origin": "day_0_00:00",
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
