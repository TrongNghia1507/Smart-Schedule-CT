from .ai.advisor import apply_fallback, enrich_options
from .models import ConflictReport, Option
from .strategies.options import (
    compress_candidates,
    exclude_candidates,
    relax_candidates,
    relaxation_blocks,
    remove_change,
)
from .errors import SolverInconclusive
from .schedule_view import build_full_schedule
STRATEGIES = [
    (1, "EXCLUDE_FROM_WEEK", exclude_candidates),
    (2, "COMPRESS_CURRENT_TASK", compress_candidates),
    (3, "CONSTRAINT_RELAXATION", relax_candidates),
]


def optimized_compression(context, target, scheduler):
    if not target.allow_compress:
        return

    if target.remaining_min <= target.min_remaining_min:
        return

    from .scheduler import CoreScheduler

    engine = CoreScheduler(
        time_limit=scheduler.time_limit
    )

    result = engine.plan(
        context,
        compress_id=target.id,
        compression_min=target.min_remaining_min,
    )

    if result.status != "FEASIBLE":
        return

    duration = sum(
        chunk.end - chunk.start
        for chunk in result.chunks
        if chunk.task_id == target.id
    )

    candidate = context.model_copy(deep=True)

    task = next(
        task
        for task in candidate.tasks
        if task.id == target.id
    )

    task.remaining_min = duration

    maximum_proven = engine.last_status == "OPTIMAL"

    description = (
        f"Giảm {target.name}: "
        f"{target.remaining_min} → {duration} phút. "
    )

    if maximum_proven:
        description += "Đây là mức tối đa đã chứng minh."
    else:
        description += (
            "Đây là mức khả thi; hết thời gian "
            "trước khi chứng minh tối đa."
        )

    yield (
        candidate,
        {
            "operation": "COMPRESS_TASK",
            "task_id": target.id,
            "old_duration": target.remaining_min,
            "new_duration": duration,
            "duration_reduced_minutes": (
                target.remaining_min - duration
            ),
            "maximum_proven": maximum_proven,
        },
        description,
        [
            "Giảm thời lượng có thể làm giảm "
            "phạm vi công việc."
        ],
    )

def optimized_relaxation(context, target, scheduler):
    from .scheduler import CoreScheduler

    blocks, sources = relaxation_blocks(context, target)

    can_remove = any(block.removable is not None for block in blocks)
    can_widen = any(
        block.left_max or block.right_max for block in blocks
    )

    if not (can_remove or can_widen):
        return

    # Bài toán có thêm biến nới nên cho solver nhiều thời gian hơn.
    engine = CoreScheduler(
        time_limit=max(scheduler.time_limit, 3.0)
    )

    result, cuts, removed_keys = engine.plan_relaxed(
        context,
        blocks,
        step=context.policy.compression_step_minutes,
    )

    if result.status != "FEASIBLE":
        return

    candidate = context.model_copy(deep=True)
    changes = []

    # 1. Xóa các lần diễn ra (kèm chuẩn bị/đi về), sát deadline trước.
    groups = {}

    for fixed in context.fixed_tasks:
        groups.setdefault(fixed.group or fixed.id, []).append(fixed)

    removed = sorted(
        (
            (key, groups[key])
            for key in removed_keys
            if key in groups
        ),
        key=lambda item: -min(
            piece.interval.start for piece in item[1]
        ),
    )

    removed_minutes = 0

    for key, pieces in removed:
        change = remove_change(key, pieces)
        changes.append(change)
        removed_minutes += change["removed_minutes"]

    dropped_ids = {
        task_id
        for change in changes
        for task_id in change["task_ids"]
    }

    candidate.fixed_tasks = [
        fixed
        for fixed in candidate.fixed_tasks
        if fixed.id not in dropped_ids
    ]

    # 2. Nới giờ thức/ngủ, sát deadline trước.
    widened = {}

    for index in sorted(cuts):
        left, right = cuts[index]

        if not left and not right:
            continue

        source = sources[index]

        if source[0] != "gap":
            continue

        _, before, after = source

        if left and before is not None:
            candidate.active_windows[before].end += left
            widened.setdefault(before, [0, 0])[1] += left

        if right and after is not None:
            candidate.active_windows[after].start -= right
            widened.setdefault(after, [0, 0])[0] += right

    widened_minutes = 0

    for index in sorted(widened, reverse=True):
        earlier, later = widened[index]
        window = candidate.active_windows[index]
        widened_minutes += earlier + later

        changes.append(
            {
                "operation": "EXPAND_ACTIVE_WINDOW",
                "window_index": index,
                "new_start": window.start,
                "new_end": window.end,
                "earlier_minutes": earlier,
                "later_minutes": later,
            }
        )

    if not changes:
        return

    proven = engine.last_status == "OPTIMAL"

    description = (
        f"Nới ràng buộc: xóa {len(removed)} sự kiện cố định "
        f"({removed_minutes} phút), "
        f"mở rộng {len(widened)} khung giờ thức "
        f"({widened_minutes} phút). "
    )

    if proven:
        description += "Đây là phương án nới ít tốn nhất đã chứng minh."
    else:
        description += (
            "Đây là mức nới khả thi; hết thời gian "
            "trước khi chứng minh ít tốn nhất."
        )

    # Phần tử thứ 5: lịch đã xếp đủ, resolve() dùng làm preview
    # mà không giải lại.
    yield (
        candidate,
        {
            "changes": changes,
            "minimal_proven": proven,
        },
        description,
        [
            "Cần người dùng chọn trước khi xóa sự kiện "
            "hoặc đổi giờ sinh hoạt."
        ],
        result,
    )


def compute_deficit(context, target, scheduler, baseline):
    """Số phút thiếu thật của target."""
    if scheduler.name != "core-cp-sat":
        return sum(baseline.unscheduled.values())

    placeable = scheduler.max_placeable(context, target.id)

    return target.remaining_min - placeable
async def resolve(context, scheduler, settings):
    target = next(
        task
        for task in context.tasks
        if task.id == context.target_task_id
    )

    baseline = scheduler.plan(context)
    if baseline.status == "UNKNOWN":
        raise SolverInconclusive(
            "Chưa phân tích được conflict: solver hết thời gian."
            )

    if baseline.status == "FEASIBLE":
        return ConflictReport(
            conflict_id=context.conflict_id,
            schedule_version=context.schedule_version,
            status="NO_CONFLICT",
            deficit_minutes=0,
            ai_status="NOT_NEEDED",
            verification_engine=scheduler.name,
            options=[],
        )

    options = []

    for option_id, option_type, generator in STRATEGIES:
        option = Option(
            option_id=option_id,
            type=option_type,
            unavailable_reason=(
                "Chưa tìm được phương án hợp lệ "
                "trong phạm vi tìm kiếm hiện tại."
            ),
            factual_description=(
                "Không có phương án đã được "
                "engine kiểm chứng."
            ),
        )

        candidates = generator(context, target)

        if scheduler.name == "core-cp-sat":
            if option_id == 2:
                candidates = optimized_compression(
                    context,
                    target,
                    scheduler,
                )
            elif option_id == 3:
                candidates = optimized_relaxation(
                    context,
                    target,
                    scheduler,
                )

        for candidate_data in candidates:
            (
                candidate,
                payload,
                description,
                warnings,
                *extra,
            ) = candidate_data

            verified = extra[0] if extra else None

            if candidate.tasks:
                if verified is not None:
                    # Option 3 (core): lịch này do chính lần giải nới tìm ra.
                    result = verified

                elif (
                    option_id == 2
                    and scheduler.name == "core-cp-sat"
                ):
                    from .scheduler import CoreScheduler

                    engine = CoreScheduler(
                        backward=True,
                        time_limit=scheduler.time_limit,
                    )

                    result = engine.plan(candidate)
                else:
                    result = scheduler.plan(candidate)

                # Toàn bộ task được giữ phải xếp đủ.
                if result.status != "FEASIBLE":
                    continue

                preview = result.chunks

            else:
                preview = []

            option.is_available = True
            option.unavailable_reason = None
            option.action_payload = payload
            option.factual_description = description
            option.preview = preview
            option.full_schedule = build_full_schedule(
                candidate,
                preview,
            )
            option.active_windows = [
                window.model_copy()
                for window in candidate.active_windows
            ]

            option.warnings = [
                *warnings,
                (
                    "Lịch xem trước có thể sắp xếp lại "
                    "các task linh hoạt trong tương lai."
                ),
            ]

            break

        options.append(option)

    apply_fallback(options, target.mandatory)

    ai_status = await enrich_options(
        options,
        target,
        settings,
    )

    return ConflictReport(
        conflict_id=context.conflict_id,
        schedule_version=context.schedule_version,
        status="CONFLICT",
        deficit_minutes=compute_deficit(
            context,
            target,
            scheduler,
            baseline,
        ),
        ai_status=ai_status,
        verification_engine=scheduler.name,
        options=options,
    )