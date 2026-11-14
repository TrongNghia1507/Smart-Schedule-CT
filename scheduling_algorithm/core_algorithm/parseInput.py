from __future__ import annotations
import json
from .models import Config, Task, FixedTask

DEFAULT_MIN_CHUNK = 30


def round_up(x: int, step: int) -> int:
    return -(-x // step) * step


def round_down(x: int, step: int) -> int:
    return x // step * step


def parse_config(raw: dict, *, now: int = 0) -> Config:
    return Config(
        day_start=raw["day_start"],
        day_end=raw["day_end"],
        num_days=7,
        time_limit=raw.get("time_limit", 10.0),
        slot_minutes=raw.get("step", 5),
        objective=raw.get("objective", {}),
        break_minutes=raw.get("break_minutes", 10),
        now=now,
        daily_cap=raw.get("daily_cap"),
        high_cap=raw.get("high_cap"),
    )


def parse_task(raw: dict, cfg: Config) -> Task:
    s = cfg.slot_minutes
    duration = round_up(raw["remaining"], s)
    splittable = not raw.get("no_break", False)

    if splittable:
        min_chunk = min(round_up(raw.get("min_chunk", DEFAULT_MIN_CHUNK), s), duration)
        max_chunk = min(round_down(raw.get("max_chunk", duration), s), duration)
    else:
        min_chunk = max_chunk = duration

    return Task(
        id=raw["task_id"],
        name=raw["name"],
        duration=duration,
        priority=raw.get("importance", 1),
        deadline=round_down(raw["deadline"], s),
        earliest_start=round_up(raw.get("earliest_start", 0), s),
        splittable=splittable,
        min_chunk=min_chunk,
        max_chunk=max_chunk,
        break_minutes=raw.get("break", cfg.break_minutes),
        buffer_minutes=raw.get("buffer", 0),
        kind=raw.get("kind", "soft"),
        focus=raw.get("focus", "low"),
    )

def parse_fixed(raw_list: list[dict], cfg: Config) -> list[FixedTask]:
    s = cfg.slot_minutes
    return [
        FixedTask(
            id=raw["task_id"],
            name=raw["name"],
            start=round_down(raw["start"], s),
            end=round_up(raw["end"], s),
        )
        for raw in raw_list
    ]

def parse_input(path: str) -> tuple[list[Task], Config, list[FixedTask]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    if data.get("schema") != "validate_result/1":
        raise ValueError("Input must use schema 'validate_result/1'.")

    cfg = parse_config(data["config"], now=data.get("now", 0))
    tasks = [parse_task(raw, cfg) for raw in data["tasks"]]
    fixed = parse_fixed(data.get("fixed", []), cfg)
    return tasks, cfg, fixed
