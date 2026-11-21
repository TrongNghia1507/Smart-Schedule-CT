"""MODULE B — CHIA PHÚT.  split_minutes(raw) -> danh sách task của từng ngày kèm số phút của task đó."""
from __future__ import annotations

from .allocate import plan_days_levels
from .models import DAY
from .normalizer import DOW, normalize
from .pipeline import from_unplaced
from .report import explain
from .timeline import gaps_of_day, make_gaps
from .validate import _subtract


def split_minutes(raw: dict, answers=None, tweak=None) -> dict:
    """tweak: hàm tùy chọn inst -> inst chạy sau normalize (vd áp buffer/chunk riêng của GUI)."""
    inst, issues = normalize(raw, answers)
    if inst is None or any(i.level in ("ERROR", "ASK") for i in issues):
        return {"status": "INVALID_INPUT", "issues": [f"{i.level} {i.code}: {i.message}" for i in issues]}
    if tweak:
        inst = tweak(inst)
    gaps = make_gaps(inst.fixed, inst.cfg, inst.now)
    rng: dict = {}
    plan, failed, _ = plan_days_levels(inst.tasks, gaps, inst.cfg, inst.now, ranges_out=rng)   # ideal range theo khoảng trống
    name = {t.id: t.name for t in inst.tasks}
    clock = lambda m: f"{m % DAY // 60:02d}:{m % DAY % 60:02d}"
    days = []
    for d in range(7):
        items = []
        for tid, m in plan.items():
            if d not in m:
                continue
            r = rng[tid]["ranges"].days[d]
            items.append({"task": name[tid], "minutes": m[d], "lo": r.lo, "hi": r.hi, "target": r.target,
                          "fits": [{"gap": f"{clock(f.gap[0])}-{clock(f.gap[1])}", "work": f.work,
                                    "chunks": [f"{clock(a)}-{clock(b)}" for a, b in f.chunks],
                                    "wasted_in_gap": f.waste} for f in r.fits]})
        before = gaps_of_day(gaps, d)
        after = list(before)
        for tid in plan:
            if d in plan[tid]:
                for f in rng[tid]["ranges"].days[d].fits:
                    after = _subtract(after, f.chunks[0][0], f.used_end)
        fmt_g = lambda gs: [f"{clock(a)}-{clock(b)} ({b - a}′)" for a, b in gs]
        days.append({"day": DOW[d], "tasks": items, "total_min": sum(i["minutes"] for i in items),
                     "free_before": fmt_g(before), "free_after": fmt_g(after),
                     "free_before_min": sum(b - a for a, b in before), "free_after_min": sum(b - a for a, b in after)})
    out = {"status": "OK" if not failed else "CANNOT_SPLIT", "days": days,
           "not_split": [{"task": name[f.task_id], "missing_min": f.missing} for f in failed]}
    if failed:      # chỗ lẽ ra gọi conflict resolver: chỉ trả về mô tả xung đột (cùng format với validate_week), KHÔNG giải quyết
        c = from_unplaced(failed[0], inst.tasks, inst.cfg, inst.now)
        out["conflict"] = explain(c, inst.tasks, inst.fixed, inst.cfg, inst.now, inst.week_start, "SPLIT", failed[0].missing).dto()
    return out


def show(r: dict) -> str:
    if r["status"] == "INVALID_INPUT":
        return "\n".join(r["issues"])
    out = []
    for d in r["days"]:
        out.append(f"\n{d['day']}  (xếp {d['total_min']}′)")
        out.append(f"  Trống TRƯỚC khi xếp ({d['free_before_min']}′): " + (", ".join(d["free_before"]) or "—"))
        for i in d["tasks"]:
            out.append(f"  - {i['task']}: lo {i['lo']} / hi {i['hi']} / target {i['target']}")
            for f in i["fits"]:
                out.append(f"       gap {f['gap']} → " + " + ".join(f["chunks"]) + f"   (gap còn lại {f["wasted_in_gap"]}′ sau chunk + break)")
        out.append(f"  Trống SAU khi xếp ({d['free_after_min']}′): " + (", ".join(d["free_after"]) or "—"))
    out += [f"\nKHÔNG CHIA ĐƯỢC: {x['task']} thiếu {x['missing_min']}′" for x in r["not_split"]]
    return "\n".join(out)
