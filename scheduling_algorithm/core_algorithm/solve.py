from __future__ import annotations

from ortools.sat.python import cp_model

from .models import Task, Config, FixedTask, SolveResult
from .context import Chunk, Ctx
from .criteria import CRITERIA


SCALE = 10**7
DEFAULT_OBJECTIVE = {"max_priority": 1}


def add_fixed(
    model,
    fixed: list[FixedTask],
    cfg: Config,
) -> list:
    spd = cfg.slots_per_day
    intervals = []

    for i, item in enumerate(fixed):
        base = item.day * spd
        start = base + cfg.to_slot(item.start)
        end = base + cfg.to_slot(item.end)

        intervals.append(
            model.NewIntervalVar(
                start,
                end - start,
                end,
                f"fixed_{i}",
            )
        )

    return intervals


def build_task(
    model,
    task: Task,
    cfg: Config,
    present,
    duration_var=None,
):
    spd = cfg.slots_per_day
    win_start = cfg.to_slot(cfg.day_start)
    win_end = cfg.to_slot(cfg.day_end)
    horizon = cfg.horizon_slots

    duration = cfg.to_slot(task.duration)

    deadline = (
        cfg.to_slot(task.deadline)
        if task.deadline is not None
        else horizon
    )

    if task.splittable:
        min_chunk = cfg.to_slot(task.min_chunk)
        max_chunk = cfg.to_slot(task.max_chunk)
        max_pieces = max(1, duration // min_chunk)
    else:
        min_chunk = max_chunk = duration
        max_pieces = 1

    # Khi thời lượng mới nhỏ hơn chunk_min,
    # cho phép một chunk bằng toàn bộ thời lượng mới.
    if duration_var is not None:
        effective_min = model.NewIntVar(
            1,
            min_chunk,
            f"minimum_{task.id}",
        )
        model.AddMinEquality(
            effective_min,
            [min_chunk, duration_var],
        )
        min_chunk = effective_min

    chunks = []

    for index in range(max_pieces):
        tag = f"{task.id}_{index}"

        used = model.NewBoolVar(f"used_{tag}")

        start = model.NewIntVar(
            0, horizon, f"start_{tag}"
        )
        length = model.NewIntVar(
            0, max_chunk, f"len_{tag}"
        )
        end = model.NewIntVar(
            0, horizon, f"end_{tag}"
        )
        day = model.NewIntVar(
            0, cfg.num_days - 1, f"day_{tag}"
        )

        model.Add(end == start + length)

        model.Add(
            length >= min_chunk
        ).OnlyEnforceIf(used)

        model.Add(
            length == 0
        ).OnlyEnforceIf(used.Not())

        model.Add(
            start == 0
        ).OnlyEnforceIf(used.Not())

        model.Add(
            day == 0
        ).OnlyEnforceIf(used.Not())

        model.Add(
            start >= day * spd + win_start
        ).OnlyEnforceIf(used)

        model.Add(
            end <= day * spd + win_end
        ).OnlyEnforceIf(used)

        model.Add(
            start >= cfg.to_slot(task.earliest_start)
        ).OnlyEnforceIf(used)

        model.Add(
            end + cfg.to_slot(task.buffer_min) <= deadline
        ).OnlyEnforceIf(used)

        model.AddImplication(used, present)

        chunks.append(
            Chunk(used, start, length, end, day)
        )

    model.Add(chunks[0].used == present)

    for previous, current in zip(chunks, chunks[1:]):
        model.AddImplication(
            current.used,
            previous.used,
        )
        model.Add(
            current.start >= previous.end
        ).OnlyEnforceIf(current.used)

    required_duration = (
        duration_var
        if duration_var is not None
        else duration
    )

    model.Add(
        sum(chunk.length for chunk in chunks)
        == required_duration
    ).OnlyEnforceIf(present)

    finish = model.NewIntVar(
        0,
        horizon,
        f"finish_{task.id}",
    )

    model.AddMaxEquality(
        finish,
        [chunk.end for chunk in chunks],
    )

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
        score, bound = CRITERIA[name](ctx)
        bound = max(bound, 1)

        coefficient = weight * max(
            1,
            SCALE // bound,
        )

        terms.append(coefficient * score)
        scores[name] = (score, bound)

    model.Maximize(sum(terms))

    return scores

def stepped(model, maximum, step, name):
    """Lượng nới là bội của step, hoặc đúng bằng maximum."""
    if maximum <= 0:
        return 0

    steps = -(-maximum // step)

    count = model.NewIntVar(0, steps, f"{name}_steps")
    scaled = model.NewIntVar(0, steps * step, f"{name}_scaled")
    model.Add(scaled == count * step)

    amount = model.NewIntVar(0, maximum, name)
    model.AddMinEquality(amount, [scaled, maximum])

    return amount


def value_of(solver, item):
    return item if isinstance(item, int) else solver.Value(item)


def add_elastic(model, blocks, step):
    """Trả về (cuts, groups, cost, removed). Slot = 1 phút nên dùng phút trực tiếp.

    removed: {khóa nhóm: BoolVar}; BoolVar = 1 nghĩa là cả nhóm bị xóa.
    """
    groups = {}
    cuts = {}
    cost = []
    removed = {}

    for index, block in enumerate(blocks):
        length = block.end - block.start

        if block.removable is not None:
            key = block.removable

            if key not in removed:
                removed[key] = model.NewBoolVar(f"removed_{key}")
                # Phạt một lần cho mỗi nhóm bị xóa (đụng vào sự kiện).
                if block.touch > 0:
                    cost.append(block.touch * removed[key])

            gone = removed[key]
            interval = model.NewOptionalIntervalVar(
                block.start,
                length,
                block.end,
                gone.Not(),
                f"block_{index}",
            )
            cost.append(block.remove_price * length * gone)

            groups.setdefault(block.group, []).append(interval)
            cuts[index] = (0, 0)
            continue

        left = stepped(model, block.left_max, step, f"left_{index}")
        right = stepped(model, block.right_max, step, f"right_{index}")

        if isinstance(left, int) and isinstance(right, int):
            interval = model.NewIntervalVar(
                block.start, length, block.end, f"block_{index}"
            )
        else:
            model.Add(left + right <= length)

            # Khi cả hai đầu cùng co, `length - left - right` là tổng của
            # hai biến nên không phải biểu thức affine: dùng biến riêng.
            size = model.NewIntVar(0, length, f"size_{index}")
            model.Add(size == length - left - right)

            interval = model.NewIntervalVar(
                block.start + left,
                size,
                block.end - right,
                f"block_{index}",
            )

            left_price = (
                block.price if block.left_price is None
                else block.left_price
            )
            right_price = (
                block.price if block.right_price is None
                else block.right_price
            )
            cost.append(left_price * left + right_price * right)

            if block.touch > 0:
                touched = model.NewBoolVar(f"touched_{index}")
                model.Add(left + right >= 1).OnlyEnforceIf(touched)
                model.Add(left + right == 0).OnlyEnforceIf(touched.Not())
                cost.append(block.touch * touched)

        groups.setdefault(block.group, []).append(interval)
        cuts[index] = (left, right)

    return cuts, groups, sum(cost), removed


def add_hint(model, tasks, present, chunks, hint, cfg):
    """hint: {task_index: [(start_min, end_min), ...]}"""
    spd = cfg.slots_per_day

    for task in tasks:
        pieces = sorted(hint.get(task.id, []))

        model.AddHint(present[task.id], 1 if pieces else 0)

        for index, chunk in enumerate(chunks[task.id]):
            if index < len(pieces):
                start = cfg.to_slot(pieces[index][0])
                end = cfg.to_slot(pieces[index][1])

                model.AddHint(chunk.used, 1)
                model.AddHint(chunk.start, start)
                model.AddHint(chunk.length, end - start)
                model.AddHint(chunk.end, end)
                model.AddHint(chunk.day, start // spd)
            else:
                for var in (
                    chunk.used,
                    chunk.start,
                    chunk.length,
                    chunk.end,
                    chunk.day,
                ):
                    model.AddHint(var, 0)
def solve(
    tasks: list[Task],
    fixed: list[FixedTask],
    cfg: Config,
    *,
    require_all=False,
    backward=False,
    compress_id=None,
    compression_min=1,
    required_ids=(),
    elastic=None,   # MỚI: list[ElasticBlock]
    step=15,        # MỚI
    hint=None,      # MỚI: {task_index: [(start, end), ...]}
) -> SolveResult:
    model = cp_model.CpModel()

    present = {}
    chunks = {}
    finish = {}

    duration_var = None

    if compress_id is not None:
        target = next(
            task for task in tasks
            if task.id == compress_id
        )

        duration_var = model.NewIntVar(
            compression_min,
            target.duration - 1,
            "compressed_duration",
        )

    for task in tasks:
        present[task.id] = model.NewBoolVar(
            f"present_{task.id}"
        )

        if require_all or task.id in required_ids:
            model.Add(present[task.id] == 1)

        variable_duration = (
            duration_var
            if task.id == compress_id
            else None
        )

        chunks[task.id], finish[task.id] = build_task(
            model,
            task,
            cfg,
            present[task.id],
            variable_duration,
        )

    intervals = add_fixed(model, fixed, cfg)

    for task in tasks:
        for index, chunk in enumerate(chunks[task.id]):
            intervals.append(
                model.NewOptionalIntervalVar(
                    chunk.start,
                    chunk.length,
                    chunk.end,
                    chunk.used,
                    f"iv_{task.id}_{index}",
                )
            )

    # Buffer cũng phải tránh fixed task và các task khác.
    for task in tasks:
        if task.buffer_min <= 0:
            continue

        buffer_slots = cfg.to_slot(task.buffer_min)

        for index, chunk in enumerate(chunks[task.id]):
            intervals.append(
                model.NewOptionalIntervalVar(
                    chunk.end,
                    buffer_slots,
                    chunk.end + buffer_slots,
                    chunk.used,
                    f"buffer_{task.id}_{index}",
                )
            )

    # MỚI: chế độ nới ràng buộc. Khoảng chặn nằm trong 2 nhóm
    # (event, gap) vì chúng có thể chồng nhau về hình học;
    # mỗi nhóm một AddNoOverlap cùng với chunk và buffer.
    relax_cost = 0
    cuts = {}
    removed = {}

    if elastic is None:
        model.AddNoOverlap(intervals)
    else:
        cuts, groups, relax_cost, removed = add_elastic(
            model, elastic, step
        )

        if not groups:
            model.AddNoOverlap(intervals)

        for group in groups.values():
            model.AddNoOverlap(intervals + group)

    # Giữ cơ chế break_minutes của thuật toán cũ.
    break_slots = (
        cfg.break_minutes + cfg.slot_minutes - 1
    ) // cfg.slot_minutes

    task_intervals = []

    for task in tasks:
        for index, chunk in enumerate(chunks[task.id]):
            task_intervals.append(
                model.NewOptionalIntervalVar(
                    chunk.start,
                    chunk.length + break_slots,
                    chunk.end + break_slots,
                    chunk.used,
                    f"task_break_{task.id}_{index}",
                )
            )

    model.AddNoOverlap(task_intervals)

    context = Ctx(
        tasks,
        cfg,
        present,
        chunks,
        finish,
    )

    build_objective(model, context)

    if duration_var is not None:
        # Option 2: giữ thời lượng mới lớn nhất có thể.
        model.Maximize(duration_var)

    elif elastic is not None:
        # MỚI - Option 3: nới ít nhất (phút × giá + phạt đụng).
        model.Minimize(relax_cost)

    elif backward and require_all:
        # Đẩy lịch về phía cuối các cửa sổ khả dụng.
        model.Maximize(
            sum(
                chunk.start
                for task_chunks in chunks.values()
                for chunk in task_chunks
            )
        )

    if hint:  # MỚI
        add_hint(model, tasks, present, chunks, hint, cfg)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = cfg.time_limit

    if hint:  # MỚI
        solver.parameters.repair_hint = True

    status = solver.Solve(model)

    result = SolveResult(
        status=solver.StatusName(status),
        solve_time=solver.WallTime(),
    )

    if status in (
        cp_model.OPTIMAL,
        cp_model.FEASIBLE,
    ):
        result.objective = solver.ObjectiveValue()

        for task in tasks:
            if not solver.BooleanValue(present[task.id]):
                continue

            pieces = [
                (
                    solver.Value(chunk.start),
                    solver.Value(chunk.end),
                )
                for chunk in chunks[task.id]
                if solver.BooleanValue(chunk.used)
            ]

            result.chunks[task.id] = sorted(pieces)

        result.removed = {
            key
            for key, flag in removed.items()
            if solver.BooleanValue(flag)
        }

        for index, (left, right) in cuts.items():  # MỚI
            result.elastic[index] = (
                value_of(solver, left),
                value_of(solver, right),
            )

    return result