"""MODULE A — VALIDATE tuần.  validate_week(raw) -> PASS | CONFLICT (+ số phút/giờ thiếu)."""
from __future__ import annotations

from .normalizer import normalize
from .pipeline import from_validation
from .timeline import make_gaps
from .validate import validate_capacity
from .report import explain


def validate_week(raw: dict, answers=None, tweak=None) -> dict:
    """tweak: hàm tùy chọn inst -> inst chạy sau normalize (vd áp buffer/chunk riêng của GUI)."""
    inst, issues = normalize(raw, answers)
    if inst is None or any(i.level in ("ERROR", "ASK") for i in issues):
        return {"status": "INVALID_INPUT", "issues": [f"{i.level} {i.code}: {i.message}" for i in issues]}
    if tweak:
        inst = tweak(inst)
    gaps = make_gaps(inst.fixed, inst.cfg, inst.now)
    v = validate_capacity(inst.tasks, gaps, inst.cfg, inst.now)
    if v.ok:
        usable = sum(b - a for a, b in gaps if b - a >= 35 and b > inst.now)       # gaps shorter than min chunk+break are useless
        demand = sum(t.footprint(inst.cfg) for t in inst.tasks)
        pct = round(100 * demand / max(1, usable))
        out = {"status": "PASS", "shortage_min": 0, "shortage_hours": 0.0, "week_load_pct": pct}
        if pct >= 90:
            out["warning"] = (f"Tuần kín {pct}% thời gian trống dùng được: dù đủ tổng giờ, rất khó chia đều/xếp vừa "
                              f"(khoảng trống bị chia nhỏ). Nên bớt việc hoặc dời deadline.")
        return out
    c = from_validation(v)
    rep = explain(c, inst.tasks, inst.fixed, inst.cfg, inst.now, inst.week_start, "VALIDATE")
    return {"status": "CONFLICT", "shortage_min": c.deficit, "shortage_hours": round(c.deficit / 60, 2),
            "deadline": rep.deadline_text, "window": rep.window_text, "demand_min": rep.demand, "free_min": rep.free,
            "overflow_task": rep.tip_task, "tasks_in_window": rep.tasks, "message": rep.text}
