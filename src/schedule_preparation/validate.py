"""MVP 1: validate the week + find the ideal range of minutes of each task on each day.

validate_capacity  -> PASS or CONFLICT (+ how many minutes are missing)
ideal_range        -> for one task and each day: lo (must do) and hi (may do)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .models import DAY, STEP, Config, Task
from .timeline import Gap, free, gaps_of_day


# ------------------------------------------------------------------ 1. capacity check
@dataclass
class Validation:
    status: str                              # PASS | CONFLICT
    deficit: int = 0                         # minutes missing
    window_start: int = 0
    deadline: int = 0                        # the deadline D where the check failed
    scope_ids: List[str] = field(default_factory=list)   # tasks that must fit in [window_start, D]
    task_id: Optional[str] = None            # the task that tips it over
    demand: int = 0
    free: int = 0

    @property
    def ok(self) -> bool:
        return self.status == "PASS"


def validate_capacity(tasks: List[Task], gaps: List[Gap], cfg: Config, now: int) -> Validation:
    """For every interval [a, D]: the footprint of all tasks that live inside it must be <= free time in it.
    (a = a task's earliest start, D = a task's deadline; scanning D from early to late, so the first failure
    is the earliest deadline that is in trouble.)"""
    ts = [t for t in tasks if t.remaining > 0]
    win = {t.id: t.window(now) for t in ts}

    for t in ts:                                         # a window that is already closed
        lo, hi = win[t.id]
        if hi <= lo:
            return Validation("CONFLICT", t.footprint(cfg), lo, hi, [t.id], t.id, t.footprint(cfg), 0)

    for D in sorted({w[1] for w in win.values()}):
        for a in sorted({w[0] for w in win.values()}):
            if a >= D:
                continue
            scope = [t for t in ts if win[t.id][0] >= a and win[t.id][1] <= D]
            if not scope:
                continue
            demand = sum(t.footprint(cfg) for t in scope)
            fr = free(gaps, a, D)
            if demand > fr:
                tip = max(scope, key=lambda t: (win[t.id][1], -t.importance))
                return Validation("CONFLICT", demand - fr, a, D, [t.id for t in scope], tip.id, demand, fr)
    return Validation("PASS")


# ------------------------------------------------------------------ 2. ideal range per day (gap-based)
@dataclass
class GapFit:
    """How one task uses ONE gap of a day: the chunks (start, end), each followed by its break; buffer after the last."""
    gap: Tuple[int, int]
    work: int
    chunks: List[Tuple[int, int]]
    brk: int
    buffer: int
    used_end: int                       # first minute of the gap that is free again

    @property
    def waste(self) -> int:             # minutes of THIS gap the task leaves unusable (gap length - what it consumed)
        return (self.gap[1] - self.gap[0]) - (self.used_end - self.gap[0])


@dataclass
class DayRange:
    lo: int                             # the task MUST do at least this on that day (other days cannot take the rest)
    hi: int                             # the task MAY do at most this on that day (best fit of the gaps, energy cap, share)
    target: int = 0                     # what we actually plan for that day (balanced between days, always reachable)
    fits: List[GapFit] = field(default_factory=list)     # target placed into the gaps of that day


@dataclass
class Ranges:
    days: Dict[int, DayRange]
    total_hi: int
    feasible: bool                           # the whole task could be split into the days


def _ceil_step(x: int) -> int:
    return -(-x // STEP) * STEP


def _subtract(gaps: List[Tuple[int, int]], a: int, b: int) -> List[Tuple[int, int]]:
    out = []
    for s, e in gaps:
        if e <= a or s >= b:
            out.append((s, e))
            continue
        if s < a:
            out.append((s, a))
        if e > b:
            out.append((b, e))
    return out


class Ledger:
    """What earlier tasks already took. Keeps the REAL gaps left on each day (not only counters)."""

    def __init__(self, gaps: Optional[List[Tuple[int, int]]] = None):
        self.work = [0] * 7
        self.high = [0] * 7
        self.slots = [0] * 7
        self.gaps: Optional[Dict[int, List[Tuple[int, int]]]] = None
        if gaps is not None:
            self.gaps = {d: [] for d in range(7)}
            for s, e in gaps:
                if 0 <= s // DAY < 7:
                    self.gaps[s // DAY].append((s, e))

    def gaps_left(self, d: int) -> Optional[List[Tuple[int, int]]]:
        return None if self.gaps is None else list(self.gaps[d])

    def commit(self, task: Task, alloc: Dict[int, int], cfg: Config):
        last = max(alloc) if alloc else None
        for d, w in alloc.items():
            self.work[d] += w
            if task.focus == "high":
                self.high[d] += w
            self.slots[d] += task.slots_for(cfg, w) + (task.buffer if d == last else 0)

    def commit_fits(self, task: Task, fits_by_day: Dict[int, List[GapFit]], cfg: Config):
        self.commit(task, {d: sum(f.work for f in fs) for d, fs in fits_by_day.items()}, cfg)
        if self.gaps is not None:
            for d, fs in fits_by_day.items():
                for f in fs:
                    self.gaps[d] = _subtract(self.gaps[d], f.gap[0], f.used_end)


# ---- fitting a task into the gaps of ONE day -----------------------------------------------------------
def _gap_options(L: int, m: int, M: int, b: int, buf: int, wmax: int) -> Dict[int, int]:
    """work x (multiple of STEP) -> fewest chunks k, such that every chunk is in [m, M] and x + k*b + buf <= L."""
    out, x = {}, _ceil_step(m)
    while x <= wmax and x + b + buf <= L:
        k = -(-x // M)
        if x >= k * m and x + k * b + buf <= L:
            out[x] = k
        x += STEP
    return out


def _useless(left: int, m: int, b: int) -> int:
    """what a gap keeps after a task used part of it: counts as waste only if it is too short for any later chunk."""
    return left if left < m + b else 0


def _reach(gaps: List[Tuple[int, int]], m: int, M: int, b: int, buf: int, wmax: int) -> dict:
    """Every amount of work w <= wmax that can be put into these gaps, with the placement that wastes the least.
    Result: w -> (waste, n_chunks, picks) ; picks = ((gap_index, x, k, closes_with_buffer), ...).
    buf > 0: the LAST used gap must also keep `buf` free minutes after its last chunk (task buffer)."""
    dp: dict = {(0, False): (0, 0, ())}

    def relax(tab, key, val):
        if key not in tab or val[:2] < tab[key][:2]:
            tab[key] = val

    for gi, (s, e) in enumerate(gaps):
        L = e - s
        o0 = _gap_options(L, m, M, b, 0, wmax)
        ob = _gap_options(L, m, M, b, buf, wmax) if buf else {}
        new = dict(dp)
        for (w, closed), (wa, nc, pk) in dp.items():
            if closed:
                continue
            for x, k in o0.items():
                if w + x <= wmax:
                    relax(new, (w + x, False), (wa + _useless(L - (x + k * b), m, b), nc + k, pk + ((gi, x, k, False),)))
            for x, k in ob.items():
                if w + x <= wmax:
                    relax(new, (w + x, True), (wa + _useless(L - (x + k * b + buf), m, b), nc + k, pk + ((gi, x, k, True),)))
        dp = new
    if buf:
        return {w: v for (w, c), v in dp.items() if c and w > 0}
    return {w: v for (w, c), v in dp.items() if not c}


def _layout(task: Task, cfg: Config, gaps: List[Tuple[int, int]], picks) -> List[GapFit]:
    brk, fits = task.brk(cfg), []
    for gi, x, k, closes in picks:
        gs, ge = gaps[gi]
        units, cur = x // STEP, gs
        base, extra = divmod(units, k)
        chunks = []
        for i in range(k):
            size = (base + (1 if i < extra else 0)) * STEP        # bigger chunks first
            chunks.append((cur, cur + size))
            cur += size + brk
        if closes:
            cur += task.buffer
        fits.append(GapFit((gs, ge), x, chunks, brk, task.buffer if closes else 0, cur))
    return fits


def ideal_range(task: Task, gaps: List[Gap], cfg: Config, now: int, ledger: Optional[Ledger] = None,
                level: int = 0) -> Ranges:
    """Gap-based ideal range. For every day of the task's window:
         gaps_d  = the free gaps of that day (minus what earlier tasks already took)
         reach_d = every amount of work that fits into those gaps with all chunks in [min_chunk, max_chunk]
                   (a 25' gap or a gap shorter than min_chunk + break gives nothing)
         hi_d    = biggest reachable amount (<= energy cap, share of the day)
         lo_d    = what day d must carry = remaining - sum of hi on the other days (rounded up to a reachable amount)
         target_d= balanced split (asap: earliest days first) using ONLY reachable amounts
         fits_d  = how target_d is laid into the gaps: each gap gets the best fitting chunks (least wasted minutes)
       level 0 = normal energy caps + share; 1 = relaxed caps, no share; 2 = only the real free time."""
    led = ledger or Ledger()
    rem = task.remaining
    lo_t, hi_t = task.window(now)
    days = [d for d in range(lo_t // DAY, (hi_t - 1) // DAY + 1) if 0 <= d < 7]
    m, M, brk = min(task.min_chunk, rem), task.max_chunk, task.brk(cfg)
    dcap, hcap = ((cfg.daily_cap, cfg.high_cap), (cfg.daily_cap_relaxed, cfg.high_cap_relaxed), (10 ** 9, 10 ** 9))[level]

    def clip(gs):
        return [(max(s, lo_t), min(e, hi_t)) for s, e in gs if min(e, hi_t) > max(s, lo_t)]

    gaps_d, R0, Rb, his = {}, {}, {}, {}
    for d in days:
        full = clip(gaps_of_day(gaps, d))
        left = led.gaps_left(d)
        gs = clip(left) if left is not None else full
        if task.kind == "soft":                                   # Soft work keeps a share of every gap empty
            gs = [(s, s + int((e - s) * (1 - cfg.soft_reserve)) // STEP * STEP) for s, e in gs]
            gs = [g for g in gs if g[1] > g[0]]
        cap = dcap - led.work[d]
        if task.focus == "high":
            cap = min(cap, hcap - led.high[d])
        if level == 0:
            cap = min(cap, max(int(cfg.task_share * sum(e - s for s, e in full)), m))
        wmax = min(max(0, cap), rem) // STEP * STEP
        gaps_d[d] = gs
        R0[d] = _reach(gs, m, M, brk, 0, wmax) if wmax >= m else {0: (0, 0, ())}
        Rb[d] = _reach(gs, m, M, brk, task.buffer, wmax) if task.buffer and wmax >= m else R0[d]
        his[d] = max(R0[d])

    total = sum(his.values())
    if total < rem:                                           # cannot fit: lo has no meaning
        return Ranges({d: DayRange(0, his[d]) for d in days}, total, False)

    los, start = {}, {}
    for d in days:
        x = max(0, rem - (total - his[d]))
        los[d] = min((w for w in R0[d] if w >= x), default=his[d])                # shown: round UP to reachable
        start[d] = max((w for w in R0[d] if w <= x), default=0)                   # used : round DOWN (never overshoot)

    def polish(a, hi_eff):
        """move 5-30' between two days while that lowers the useless leftover of the gaps (balance stays close)."""
        cost = lambda d, w: R0[d][w][0] if w in R0[d] else None
        for _ in range(50):
            best = None
            for d1 in days:
                for d2 in days:
                    if d1 == d2:
                        continue
                    for dl in range(STEP, 35, STEP):
                        n1, n2 = a[d1] - dl, a[d2] + dl
                        c1, c2 = cost(d1, n1), cost(d2, n2)
                        if n1 < 0 or c1 is None or c2 is None or n2 > hi_eff[d2]:
                            continue
                        gain = cost(d1, a[d1]) + cost(d2, a[d2]) - c1 - c2
                        if gain > 0 and (best is None or gain > best[0]):
                            best = (gain, d1, d2, n1, n2)
            if best is None:
                return
            _, d1, d2, n1, n2 = best
            a[d1], a[d2] = n1, n2

    hi_eff = dict(his)
    for _ in range(20):                                       # fill, then make sure the buffer fits the last day
        a, left = dict(start), rem - sum(start.values())
        while left > 0:
            best = None
            for d in days:
                reach = sorted(w for w in R0[d] if a[d] < w <= min(hi_eff[d], a[d] + left))
                if not reach:
                    continue
                if task.kind == "asap":
                    key, w = (d,), reach[-1]                  # earliest day first, as much as fits
                else:
                    key, w = (led.work[d] + a[d], d), reach[0]    # lightest day first
                if best is None or key < best[0]:
                    best = (key, d, w)
            if best is None:
                break
            _, d, w = best
            left -= w - a[d]
            a[d] = w
        if left > 0:                                          # granularity: some minutes cannot be placed
            return Ranges({d: DayRange(los[d], his[d]) for d in days}, rem - left, False)
        polish(a, hi_eff)
        used = [d for d in days if a[d] > 0]
        last = max(used)
        if not task.buffer or a[last] in Rb[last]:
            break
        hi_eff[last] = max((w for w in Rb[last] if w < a[last]), default=0)       # last day cannot keep the buffer
        start = {d: min(start[d], hi_eff[d]) for d in days}
    else:
        return Ranges({d: DayRange(los[d], his[d]) for d in days}, rem - 1, False)

    out = {}
    for d in days:
        fits: List[GapFit] = []
        if a[d] > 0:
            tab = Rb[d] if (task.buffer and d == last) else R0[d]
            fits = _layout(task, cfg, gaps_d[d], tab[a[d]][2])
        out[d] = DayRange(los[d], his[d], a[d], fits)
    return Ranges(out, total, True)
