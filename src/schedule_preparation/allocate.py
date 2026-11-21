"""MVP 2: allocate tasks into the calendar.
  plan_days  : how many minutes each task gets on each day (inside its ideal range, balanced)
  first_fit  : put those minutes into real free gaps as chunks (work, break, buffer)
Anything that does not fit is REPORTED (unplaced), never silently dropped -> handed to collision.py."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .models import DAY, KIND_ORDER, STEP, Config, Task
from .timeline import Gap, gaps_of_day
from .validate import GapFit, Ledger, ideal_range

DayPlan = Dict[str, Dict[int, int]]


@dataclass(frozen=True)
class Block:
    task_id: str
    start: int
    end: int
    type: str            # work | break | buffer

    @property
    def minutes(self) -> int:
        return self.end - self.start


@dataclass(frozen=True)
class Unplaced:
    task_id: str
    missing: int         # work minutes that found no place
    code: str            # NO_CAPACITY (no room in the days it may use) | FRAGMENTED (room exists but too fragmented)


def order_key(t: Task):
    return (KIND_ORDER[t.kind], t.window(0)[1], -t.importance)


def sorter(order: Optional[List[str]]):
    """key function: follow an explicit order (chosen by a specialised algorithm) or the default rule"""
    if order is None:
        return order_key
    pos = {tid: i for i, tid in enumerate(order)}
    return lambda t: (pos.get(t.id, len(pos)),)


# ----------------------------------------------------------------------------- tier 1
def plan_days(tasks: List[Task], gaps: List[Gap], cfg: Config, now: int,
              order: Optional[List[str]] = None) -> Tuple[DayPlan, List[Unplaced]]:
    plan, failed, _ = plan_days_levels(tasks, gaps, cfg, now, order)
    return plan, failed


def blocks_of(tid: str, fits: List[GapFit]) -> List[Block]:
    out: List[Block] = []
    for f in fits:
        cur = f.gap[0]
        for cs, ce in f.chunks:
            out += [Block(tid, cs, ce, "work"), Block(tid, ce, ce + f.brk, "break")]
            cur = ce + f.brk
        if f.buffer:
            out.append(Block(tid, cur, cur + f.buffer, "buffer"))
    return out


def plan_days_levels(tasks: List[Task], gaps: List[Gap], cfg: Config, now: int, order: Optional[List[str]] = None,
                     ranges_out: Optional[dict] = None, blocks_out: Optional[dict] = None):
    """Per task (in priority order): ideal_range (gap based: lo / hi / target per day + how the target is laid into
    the gaps), commit it, and the next task sees only the gaps that are left.
    blocks_out[task_id] = the concrete work / break / buffer blocks."""
    ledger, plan, failed, used = Ledger(gaps), {}, [], {}
    for t in sorted((x for x in tasks if x.remaining > 0), key=sorter(order)):
        levels = (0,) if t.kind == "soft" else (0, 1, 2)     # Soft never relaxes the energy caps
        for lv in levels:
            rg = ideal_range(t, gaps, cfg, now, ledger, lv)
            if rg.feasible:
                break
        if ranges_out is not None:                       # expose lo/hi/target + the minutes finally given, for the UI
            ranges_out[t.id] = {"level": lv, "ranges": rg, "minutes": {}}
        if not rg.feasible:
            failed.append(Unplaced(t.id, t.remaining - rg.total_hi, "NO_CAPACITY"))
            continue
        used[t.id] = lv
        alloc = {d: r.target for d, r in rg.days.items() if r.target > 0}
        plan[t.id] = alloc
        fits = {d: r.fits for d, r in rg.days.items() if r.target > 0}
        ledger.commit_fits(t, fits, cfg)
        if ranges_out is not None:
            ranges_out[t.id]["minutes"] = alloc
        if blocks_out is not None:
            blocks_out[t.id] = [b for d in sorted(fits) for b in blocks_of(t.id, fits[d])]
    return plan, failed, used


def plan_week(tasks: List[Task], gaps: List[Gap], cfg: Config, now: int, order: Optional[List[str]] = None):
    """plan_days + placement in one pass: returns (plan, blocks, failed)."""
    bo: dict = {}
    plan, failed, _ = plan_days_levels(tasks, gaps, cfg, now, order, blocks_out=bo)
    return plan, sorted((b for bl in bo.values() for b in bl), key=lambda b: (b.start, b.task_id)), failed


# ----------------------------------------------------------------------------- tier 2
def first_fit(plan: DayPlan, tasks: List[Task], gaps: List[Gap], cfg: Config,
              order: Optional[List[str]] = None) -> Tuple[List[Block], List[Unplaced]]:
    """Per day, urgent tasks first, each takes the earliest gap that can hold a chunk.
    chunk = min(max_chunk, need); after every chunk one break; after the LAST chunk of the task also its buffer.
    What is left of a task on a day must be 0 or >= min_chunk (no useless slivers)."""
    byid = {t.id: t for t in tasks}
    blocks: List[Block] = []
    unplaced: Dict[str, int] = {}
    for d in range(7):
        free = [list(g) for g in gaps_of_day(gaps, d)]
        items = sorted(((tid, days[d]) for tid, days in plan.items() if d in days),
                       key=lambda x: sorter(order)(byid[x[0]]))
        for tid, need in items:
            t, brk = byid[tid], byid[tid].brk(cfg)
            last_day = max(plan[tid])
            for g in free:
                while need > 0:
                    L, m = g[1] - g[0], min(t.min_chunk, need)
                    final = d == last_day and need <= t.max_chunk and L >= need + brk + t.buffer
                    if final:
                        c = need
                    else:
                        c = min(t.max_chunk, need, L - brk) // STEP * STEP
                        rest = need - c
                        if 0 < rest < t.min_chunk:               # avoid a sliver: leave exactly min_chunk
                            c = need - t.min_chunk if need - t.min_chunk >= t.min_chunk else 0
                        if c < m:
                            break                                # this gap cannot hold a chunk
                    s = g[0]
                    blocks.append(Block(tid, s, s + c, "work"))
                    cur = s + c
                    blocks.append(Block(tid, cur, cur + brk, "break"))
                    cur += brk
                    if final and t.buffer:
                        blocks.append(Block(tid, cur, cur + t.buffer, "buffer"))
                        cur += t.buffer
                    g[0] = cur
                    need -= c
                if need == 0:
                    break
            if need > 0:
                unplaced[tid] = unplaced.get(tid, 0) + need
    return blocks, [Unplaced(tid, w, "FRAGMENTED") for tid, w in unplaced.items()]
