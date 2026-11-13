"""Free-time gaps of the week. A gap never crosses midnight."""
from __future__ import annotations

from typing import List, Tuple

from .models import DAY, STEP, Config, Fixed

Gap = Tuple[int, int]


def ceil_step(x: int) -> int:
    return -(-x // STEP) * STEP


def make_gaps(fixed: List[Fixed], cfg: Config, now: int = 0) -> List[Gap]:
    busy = sorted((f.start, f.end) for f in fixed)
    out: List[Gap] = []
    for d in range(7):
        s, e = max(d * DAY + cfg.day_start, ceil_step(now)), d * DAY + cfg.day_end
        cur = s
        for bs, be in busy:
            if be <= cur or bs >= e:
                continue
            if bs > cur:
                out.append((cur, bs))
            cur = max(cur, be)
        if cur < e:
            out.append((cur, e))
    return out


def free(gaps: List[Gap], a: int, b: int) -> int:
    """free minutes inside [a, b)"""
    return sum(max(0, min(e, b) - max(s, a)) for s, e in gaps)


def gaps_of_day(gaps: List[Gap], d: int, a: int = 0, b: int = 10 ** 9) -> List[Gap]:
    out = []
    for s, e in gaps:
        if s // DAY == d:
            s, e = max(s, a), min(e, b)
            if e > s:
                out.append((s, e))
    return out
