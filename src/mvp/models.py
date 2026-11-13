"""Data objects shared by every module. Frozen = a module can never change another module's data."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

DAY = 1440
WEEK = 7 * DAY
STEP = 5
KIND_ORDER = {"asap": 0, "hard": 1, "soft": 2}           # processing order
KIND_PROTECT = {"hard": 2, "asap": 1, "soft": 0}         # higher = protect more


@dataclass(frozen=True)
class Config:
    day_start: int = 7 * 60          # earliest minute of a day usable for work
    day_end: int = 23 * 60           # latest minute of a day usable for work
    daily_cap: int = 360             # sustainable work minutes per day
    high_cap: int = 180              # ... for focus=high work
    daily_cap_relaxed: int = 480     # level 1 (hard/asap only, when level 0 cannot fit)
    high_cap_relaxed: int = 240
    task_share: float = 0.5          # one task may take at most this share of a day's free time
    soft_reserve: float = 0.15       # share of free time Soft work leaves empty
    break_high: int = 10
    break_low: int = 5


@dataclass(frozen=True)
class Fixed:
    id: str
    name: str
    start: int
    end: int
    min_elastic: Optional[int] = None    # shortest it may be shrunk to (None = cannot shrink)
    type: str = "other"                  # study | meal | leisure | sleep | attend | prep | other


@dataclass(frozen=True)
class Task:
    id: str
    name: str
    kind: str                         # asap | hard | soft
    importance: int                   # 1..10
    deadline: int
    remaining: int                    # work minutes still needed
    focus: str = "low"                # high | low
    min_chunk: int = 30
    max_chunk: int = 90
    buffer: int = 0                   # minutes kept free after the last chunk
    earliest_start: int = 0
    after: tuple = ()                 # ids that must be finished first (order constraint)
    no_break: bool = False            # one whole block (e.g. a 1h run): no break after it

    # ---- derived quantities ------------------------------------------------
    def brk(self, cfg: Config) -> int:
        if self.no_break:
            return 0
        return cfg.break_high if self.focus == "high" else cfg.break_low

    def window(self, now: int):
        lo = max(now, self.earliest_start)
        hi = min(self.deadline, WEEK)           # asap also has a deadline; it only differs in how it is placed
        return lo, hi

    def slots_for(self, cfg: Config, work: int) -> int:
        """free minutes needed to place `work` minutes: work + one break per chunk."""
        return work + math.ceil(work / self.max_chunk) * self.brk(cfg) if work > 0 else 0

    def footprint(self, cfg: Config) -> int:
        return self.slots_for(cfg, self.remaining) + self.buffer

    def protect_key(self):
        """bigger = more protected. Used by Resolver to choose what to postpone first."""
        return (KIND_PROTECT[self.kind], self.importance)


def work_for_slots(task: Task, cfg: Config, slots: int) -> int:
    """largest work (multiple of STEP) whose work + breaks fit in `slots` free minutes."""
    mx, brk = task.max_chunk, task.brk(cfg)
    full, rest = divmod(max(0, slots), mx + brk)
    w = full * mx + (min(mx, rest - brk) if rest > brk else 0)
    return w // STEP * STEP
