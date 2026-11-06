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


async def resolve(context, scheduler, settings):
    target = next(
        task for task in context.tasks
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
                "Không có phương án đã được engine kiểm chứng."
            ),
        )

        for index, candidate_data in enumerate(generator(context, target)):
            # Giới hạn số lần gọi engine cho mỗi nhóm.
            if index >= 120:
                break

            candidate, payload, description, warnings = candidate_data

            if candidate.tasks:
                result = scheduler.plan(candidate)

                # Kiểm chứng TOÀN BỘ công việc còn giữ.
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

            # Chọn ứng viên khả thi đầu tiên của nhóm.
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
        deficit_minutes=sum(baseline.unscheduled.values()),
        ai_status=ai_status,
        verification_engine=scheduler.name,
        options=options,
    )