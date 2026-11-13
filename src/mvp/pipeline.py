"""Glue: validate -> ranges/plan_days -> first_fit. Returns either a schedule or a Conflict for collision.py."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .allocate import Block, Unplaced, plan_week
from .models import Config, Fixed, Task
from .timeline import make_gaps
from .validate import Validation, validate_capacity


@dataclass
class Conflict:
    task_id: str                 # the task that does not fit
    deficit: int                 # minutes missing
    window_start: int
    deadline: int
    scope_ids: List[str]         # tasks competing for the same time
    reason: str = "NO_CAPACITY"  # NO_CAPACITY | FRAGMENTED


@dataclass
class Outcome:
    status: str                  # OK | CONFLICT
    blocks: List[Block] = field(default_factory=list)
    day_plan: dict = field(default_factory=dict)
    conflict: Optional[Conflict] = None

    @property
    def ok(self) -> bool:
        return self.status == "OK"


def _scope(tasks: List[Task], x: Task, now: int) -> List[str]:
    a, D = x.window(now)
    return [t.id for t in tasks if t.remaining > 0 and t.window(now)[0] >= a and t.window(now)[1] <= D]


def from_validation(v: Validation) -> Conflict:
    return Conflict(v.task_id, v.deficit, v.window_start, v.deadline, v.scope_ids, "NO_CAPACITY")


def from_unplaced(u: Unplaced, tasks: List[Task], cfg: Config, now: int) -> Conflict:
    x = next(t for t in tasks if t.id == u.task_id)
    a, D = x.window(now)
    deficit = x.footprint(cfg) - x.slots_for(cfg, max(0, x.remaining - u.missing)) - x.buffer if u.missing < x.remaining \
        else x.footprint(cfg)
    return Conflict(x.id, max(deficit, u.missing), a, D, _scope(tasks, x, now), u.code)


def run_core(tasks: List[Task], fixed: List[Fixed], cfg: Config, now: int) -> Outcome:
    gaps = make_gaps(fixed, cfg, now)
    v = validate_capacity(tasks, gaps, cfg, now)
    if not v.ok:
        return Outcome("CONFLICT", conflict=from_validation(v))
    plan, blocks, failed = plan_week(tasks, gaps, cfg, now)       # ideal range (gap based) -> chunks in the gaps
    if failed:
        return Outcome("CONFLICT", blocks, plan, from_unplaced(failed[0], tasks, cfg, now))
    return Outcome("OK", blocks, plan)
