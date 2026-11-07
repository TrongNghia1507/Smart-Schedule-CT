from __future__ import annotations
from ortools.sat.python import cp_model
from models import Task, Config, FixedTask, SolveResult
from context import Chunk, Ctx
from criteria import CRITERIA

SCALE = 10**7
DEFAULT_OBJECTIVE = {"max_priority": 1}

def add_fixed(model, fixed: list[FixedTask], cfg: Config) -> list:
    spd = cfg.slots_per_day
    intervals = []
    for i, f in enumerate(fixed):
        base = f.day * spd
        s = base + cfg.to_slot(f.start)
        e = base + cfg.to_slot(f.end)
        intervals.append(model.NewIntervalVar(s, e - s, e, f"fixed_{i}"))
    return intervals

def build_task(model, t: Task, cfg: Config, present):
    spd = cfg.slots_per_day
    win_start = cfg.to_slot(cfg.day_start)
    win_end = cfg.to_slot(cfg.day_end)
    horizon = cfg.horizon_slots
    dur = cfg.to_slot(t.duration)
    deadline = cfg.to_slot(t.deadline) if t.deadline is not None else horizon

    if t.splittable:
        min_c = cfg.to_slot(t.min_chunk)
        max_c = cfg.to_slot(t.max_chunk)
        k_max = max(1, dur // min_c)
    else:
        min_c = max_c = dur
        k_max = 1

    chunks = []
    for k in range(k_max):
        tag = f"{t.id}_{k}"
        used = model.NewBoolVar(f"used_{tag}")
        start = model.NewIntVar(0, horizon, f"start_{tag}")
        length = model.NewIntVar(0, max_c, f"len_{tag}")
        end = model.NewIntVar(0, horizon, f"end_{tag}")
        day = model.NewIntVar(0, cfg.num_days - 1, f"day_{tag}")

        model.Add(end == start + length)

        model.Add(length >= min_c).OnlyEnforceIf(used)
        model.Add(length == 0).OnlyEnforceIf(used.Not())
        model.Add(start == 0).OnlyEnforceIf(used.Not())
        model.Add(day == 0).OnlyEnforceIf(used.Not())

        model.Add(start >= day * spd + win_start).OnlyEnforceIf(used)
        model.Add(end <= day * spd + win_end).OnlyEnforceIf(used)
        model.Add(end <= deadline).OnlyEnforceIf(used)

        model.AddImplication(used, present)
        chunks.append(Chunk(used, start, length, end, day))

    model.Add(chunks[0].used == present)
    for a, b in zip(chunks, chunks[1:]):
        model.AddImplication(b.used, a.used)
        model.Add(b.start >= a.end).OnlyEnforceIf(b.used)

    model.Add(sum(c.length for c in chunks) == dur).OnlyEnforceIf(present)

    finish = model.NewIntVar(0, horizon, f"finish_{t.id}")
    model.AddMaxEquality(finish, [c.end for c in chunks])

    return chunks, finish


def build_objective(model, ctx: Ctx) -> dict:
    weights = {
        name: weight
        for name, weight in (ctx.cfg.objective or {}).items()
        if weight > 0
    } or DEFAULT_OBJECTIVE

    terms = []
    scores = {}
    for name, weight in weights.items():
        if weight <= 0:
            continue
        score, bound = CRITERIA[name](ctx)
        bound = max(bound, 1)
        coef = weight * max(1, SCALE // bound)
        terms.append(coef * score)
        scores[name] = (score, bound)

    model.Maximize(sum(terms))
    return scores


def solve(tasks: list[Task], fixed: list[FixedTask], cfg: Config) -> SolveResult:
    model = cp_model.CpModel()

    present, chunks, finish = {}, {}, {}
    for t in tasks:
        present[t.id] = model.NewBoolVar(f"present_{t.id}")
        chunks[t.id], finish[t.id] = build_task(model, t, cfg, present[t.id])

    intervals = add_fixed(model, fixed, cfg)
    for t in tasks:
        for k, c in enumerate(chunks[t.id]):
            intervals.append(
                model.NewOptionalIntervalVar(c.start, c.length, c.end, c.used, f"iv_{t.id}_{k}")
            )
    model.AddNoOverlap(intervals)

    # Only task chunks receive padding; fixed intervals remain unchanged.
    # Round up to slots so the actual gap is never shorter than requested.
    break_slots = (
        cfg.break_minutes + cfg.slot_minutes - 1
    ) // cfg.slot_minutes
    task_intervals = []
    for t in tasks:
        for k, c in enumerate(chunks[t.id]):
            task_intervals.append(
                model.NewOptionalIntervalVar(
                    c.start,
                    c.length + break_slots,
                    c.end + break_slots,
                    c.used,
                    f"task_break_{t.id}_{k}",
                )
            )
    model.AddNoOverlap(task_intervals)

    ctx = Ctx(tasks, cfg, present, chunks, finish)
    build_objective(model, ctx)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = cfg.time_limit
    status = solver.Solve(model)

    result = SolveResult(status=solver.StatusName(status), solve_time=solver.WallTime())
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        result.objective = solver.ObjectiveValue()
        for t in tasks:
            if solver.BooleanValue(present[t.id]):
                pieces = [
                    (solver.Value(c.start), solver.Value(c.end))
                    for c in chunks[t.id]
                    if solver.BooleanValue(c.used)
                ]
                result.chunks[t.id] = sorted(pieces)
    return result