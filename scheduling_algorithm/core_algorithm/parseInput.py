from __future__ import annotations
import json
from models import Config, Task, FixedTask, MINUTES_PER_DAY

DEFAULT_MIN_CHUNK = 30


def parse_time(value) -> int:
    if isinstance(value, int):
        return value
    h, m = value.split(":")
    return int(h) * 60 + int(m)


def round_up(x: int, step: int) -> int:
    return -(-x // step) * step


def round_down(x: int, step: int) -> int:
    return x // step * step


def parse_config(raw: dict) -> Config:
    return Config(
        day_start=parse_time(raw["day_start"]),
        day_end=parse_time(raw["day_end"]),
        num_days=raw.get("num_days", 7),
        time_limit=raw.get("time_limit", 10.0),
        slot_minutes=raw.get("slot_minutes", 5),
        objective=raw.get("objective", {}),
        break_minutes=raw.get("break_minutes", 10),
    )


def parse_deadline(raw: dict | None, cfg: Config) -> int | None:
    if raw is None:
        return None
    absolute = raw["day"] * MINUTES_PER_DAY + parse_time(raw["time"])
    return round_down(absolute, cfg.slot_minutes)


def parse_task(raw: dict, cfg: Config) -> Task:
    s = cfg.slot_minutes
    duration = round_up(raw["duration"], s)
    splittable = raw.get("splittable", False)

    if splittable:
        min_chunk = min(round_up(raw.get("min_chunk", DEFAULT_MIN_CHUNK), s), duration)
        max_chunk = min(round_down(raw.get("max_chunk", duration), s), duration)
    else:
        min_chunk = max_chunk = duration

    return Task(
        id=raw["id"],
        name=raw["name"],
        duration=duration,
        priority=raw.get("priority", 1),
        deadline=parse_deadline(raw.get("deadline"), cfg),
        splittable=splittable,
        min_chunk=min_chunk,
        max_chunk=max_chunk,
    )

def parse_fixed(raw_list: list[dict], cfg: Config) -> list[FixedTask]:
    s = cfg.slot_minutes
    result = []
    for raw in raw_list:
        days = raw.get("days", list(range(cfg.num_days)))
        start = round_down(parse_time(raw["start"]), s)
        end = round_up(parse_time(raw["end"]), s)
        for d in days:
            result.append(FixedTask(raw["name"], d, start, end))
    return result

def parse_input(path: str) -> tuple[list[Task], Config, list[FixedTask]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    cfg = parse_config(data["config"])
    tasks = [parse_task(raw, cfg) for raw in data["tasks"]]
    fixed = parse_fixed(data.get("fixed_tasks", []), cfg)
    return tasks, cfg, fixed