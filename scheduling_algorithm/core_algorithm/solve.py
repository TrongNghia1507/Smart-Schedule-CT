from __future__ import annotations
from ortools.sat.python import cp_model
from .models import Task, Config, FixedTask, SolveResult
from .context import Chunk

def add_fixed(model, fixed: list[FixedTask], cfg: Config) -> list:
    intervals = []
    for i, f in enumerate(fixed):
        s = cfg.to_slot(f.start)
        e = cfg.to_slot(f.end)
        intervals.append(model.NewIntervalVar(s, e - s, e, f"fixed_{i}"))
    return intervals

def build_task(model, t: Task, cfg: Config, present):
    spd = cfg.slots_per_day
    win_start = cfg.to_slot(cfg.day_start)
    win_end = cfg.to_slot(cfg.day_end)
    horizon = cfg.horizon_slots
    dur = cfg.to_slot(t.duration)
    deadline = cfg.to_slot(t.deadline) if t.deadline is not None else horizon
    earliest_start = -cfg.to_slot(-max(cfg.now, t.earliest_start))

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
        model.Add(start >= earliest_start).OnlyEnforceIf(used)
        model.Add(end <= day * spd + win_end).OnlyEnforceIf(used)
        model.Add(end <= deadline).OnlyEnforceIf(used)

        model.AddImplication(used, present)
        chunks.append(Chunk(used, start, length, end, day))

    model.Add(chunks[0].used == present)
    for a, b in zip(chunks, chunks[1:]):
        model.AddImplication(b.used, a.used)
        model.Add(b.start >= a.end).OnlyEnforceIf(b.used)

    model.Add(sum(c.length for c in chunks) == dur).OnlyEnforceIf(present)

    return chunks


def add_daily_caps(model, tasks: list[Task], chunks: dict[str, list[Chunk]], cfg: Config):
    if cfg.daily_cap is None and cfg.high_cap is None:
        return

    daily_load = [[] for _ in range(cfg.num_days)]
    high_load = [[] for _ in range(cfg.num_days)]
    for task in tasks:
        if cfg.daily_cap is None and task.focus != "high":
            continue
        max_length = cfg.to_slot(task.max_chunk if task.splittable else task.duration)
        for index, chunk in enumerate(chunks[task.id]):
            assignments = []
            for day in range(cfg.num_days):
                tag = f"{task.id}_{index}_{day}"
                on_day = model.NewBoolVar(f"on_day_{tag}")
                load = model.NewIntVar(0, max_length, f"day_load_{tag}")
                model.Add(chunk.day == day).OnlyEnforceIf(on_day)
                model.Add(load == chunk.length).OnlyEnforceIf(on_day)
                model.Add(load == 0).OnlyEnforceIf(on_day.Not())
                assignments.append(on_day)
                daily_load[day].append(load)
                if task.focus == "high":
                    high_load[day].append(load)
            model.Add(sum(assignments) == chunk.used)

    for day in range(cfg.num_days):
        if cfg.daily_cap is not None:
            model.Add(sum(daily_load[day]) <= cfg.to_slot(cfg.daily_cap))
        if cfg.high_cap is not None:
            model.Add(sum(high_load[day]) <= cfg.to_slot(cfg.high_cap))


def solve(tasks: list[Task], fixed: list[FixedTask], cfg: Config) -> SolveResult:
    model = cp_model.CpModel()

    present, chunks = {}, {}
    for t in tasks:
        present[t.id] = model.NewBoolVar(f"present_{t.id}")
        chunks[t.id] = build_task(model, t, cfg, present[t.id])

    add_daily_caps(model, tasks, chunks, cfg)
    intervals = add_fixed(model, fixed, cfg)
    for t in tasks:
        for k, c in enumerate(chunks[t.id]):
            intervals.append(
                model.NewOptionalIntervalVar(c.start, c.length, c.end, c.used, f"iv_{t.id}_{k}")
            )

    # Reserve each task's buffer after its final chunk. It is a real blocked
    # interval, so no other task or fixed event can occupy that time.
    for t in tasks:
        buffer_slots = cfg.to_slot(t.buffer_minutes)
        if buffer_slots == 0:
            continue

        deadline = cfg.to_slot(t.deadline) if t.deadline is not None else cfg.horizon_slots
        task_chunks = chunks[t.id]
        for k, c in enumerate(task_chunks):
            is_last = model.NewBoolVar(f"last_{t.id}_{k}")
            if k == len(task_chunks) - 1:
                model.Add(is_last == c.used)
            else:
                next_used = task_chunks[k + 1].used
                model.AddImplication(is_last, c.used)
                model.AddImplication(is_last, next_used.Not())
                model.AddBoolOr([c.used.Not(), next_used, is_last])

            model.Add(
                c.end + buffer_slots <= c.day * cfg.slots_per_day + cfg.to_slot(cfg.day_end)
            ).OnlyEnforceIf(is_last)
            model.Add(c.end + buffer_slots <= deadline).OnlyEnforceIf(is_last)
            intervals.append(
                model.NewOptionalIntervalVar(
                    c.end,
                    buffer_slots,
                    c.end + buffer_slots,
                    is_last,
                    f"buffer_{t.id}_{k}",
                )
            )
    model.AddNoOverlap(intervals)

    # Only task chunks receive padding; fixed intervals remain unchanged.
    # A task may use its own break duration from the normalized input.
    task_intervals = []
    for t in tasks:
        break_slots = (
            t.break_minutes + cfg.slot_minutes - 1
        ) // cfg.slot_minutes
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

    model.Maximize(sum(task.priority * present[task.id] for task in tasks))

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
