from __future__ import annotations
from dataclasses import dataclass, field

MINUTES_PER_DAY = 1440


@dataclass
class Config:
    day_start: int
    day_end: int
    num_days: int = 7
    time_limit: float = 10.0
    slot_minutes: int = 5
    break_minutes: int = 10
    now: int = 0
    daily_cap: int | None = None
    high_cap: int | None = None

    @property
    def window(self) -> int:
        return self.day_end - self.day_start

    @property
    def horizon(self) -> int:
        return self.num_days * MINUTES_PER_DAY

    @property
    def slots_per_day(self) -> int:
        return MINUTES_PER_DAY // self.slot_minutes

    @property
    def horizon_slots(self) -> int:
        return self.num_days * self.slots_per_day

    def to_slot(self, minutes: int) -> int:
        return minutes // self.slot_minutes

    def to_minutes(self, slot: int) -> int:
        return slot * self.slot_minutes


@dataclass
class Task:
    id: str
    name: str
    duration: int
    priority: int = 1
    deadline: int | None = None
    earliest_start: int = 0
    splittable: bool = False
    min_chunk: int = 0
    max_chunk: int = 0
    break_minutes: int = 10
    buffer_minutes: int = 0
    kind: str = "soft"
    focus: str = "low"

@dataclass
class FixedTask:
    id: str
    name: str
    start: int
    end: int

@dataclass
class SolveResult:
    status: str
    objective: float | None = None
    chunks: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    solve_time: float = 0.0
