from .ai.advisor import apply_fallback, enrich_options
from .models import ConflictReport, Option
from .strategies.options import (
    compress_candidates,
    exclude_candidates,
    postpone_candidates,
    relax_candidates,
)


STRATEGIES = [
    (1, "EXCLUDE_FROM_WEEK", exclude_candidates),
    (2, "COMPRESS_CURRENT_TASK", compress_candidates),
    (3, "POSTPONE_OR_DEFER_TASKS", postpone_candidates),
    (4, "CONSTRAINT_RELAXATION", relax_candidates),
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


async def resolve(context, scheduler, settings):
    target = next(
        task
        for task in context.tasks
        if task.id == context.target_task_id
    )

    baseline = scheduler.plan(context)

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

        if (
            option_id == 2
            and scheduler.name == "core-cp-sat"
        ):
            candidates = optimized_compression(
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
            ) = candidate_data

            if candidate.tasks:
                if (
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

            option.warnings = [
                *warnings,
                (
                    "Lịch xem trước có thể sắp xếp lại "
                    "các task linh hoạt trong tương lai."
                ),
            ]

            break

        options.append(option)

    apply_fallback(options, target.kind)

    ai_status = await enrich_options(
        options,
        target,
        settings,
    )

    return ConflictReport(
        conflict_id=context.conflict_id,
        schedule_version=context.schedule_version,
        status="CONFLICT",
        deficit_minutes=sum(
            baseline.unscheduled.values()
        ),
        ai_status=ai_status,
        verification_engine=scheduler.name,
        options=options,
    )