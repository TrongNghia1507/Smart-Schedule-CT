from .ai.advisor import apply_fallback, enrich_options
from .models import ConflictReport, Option
from .strategies.options import (
    compress_candidates,
    compress_precheck,
    exclude_candidates,
    exclude_precheck,
    postpone_candidates,
    postpone_precheck,
    relax_candidates,
    relax_precheck,
)


STRATEGIES = [
    (1, "EXCLUDE_FROM_WEEK", exclude_candidates, exclude_precheck),
    (2, "COMPRESS_CURRENT_TASK", compress_candidates, compress_precheck),
    (3, "POSTPONE_OR_DEFER_TASKS", postpone_candidates, postpone_precheck),
    (4, "CONSTRAINT_RELAXATION", relax_candidates, relax_precheck),
]

MAX_CANDIDATES_PER_OPTION = 120


def _no_feasible_reason(generated, tested, capped):
    if generated == 0:
        return "Không sinh được ứng viên nào trong ngữ cảnh hiện tại."

    reason = (
        f"Đã kiểm chứng {tested} ứng viên bằng engine nhưng không ứng viên "
        "nào làm toàn bộ lịch khả thi."
    )

    if capped:
        reason += f" (đạt giới hạn {MAX_CANDIDATES_PER_OPTION} ứng viên)"

    return reason


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

    for option_id, option_type, generator, precheck in STRATEGIES:
        option = Option(option_id=option_id, type=option_type)

        # 1) Option có áp dụng được trong ngữ cảnh này không?
        blocked_reason = precheck(context, target)

        if blocked_reason:
            option.unavailable_reason = blocked_reason
            option.factual_description = f"Không khả dụng: {blocked_reason}"
            options.append(option)
            continue

        # 2) Có ứng viên nào được engine kiểm chứng là khả thi không?
        generated = 0
        tested = 0
        capped = False

        for index, candidate_data in enumerate(generator(context, target)):
            # Giới hạn số lần gọi engine cho mỗi nhóm.
            if index >= MAX_CANDIDATES_PER_OPTION:
                capped = True
                break

            generated += 1
            candidate, payload, description, warnings = candidate_data

            if candidate.tasks:
                tested += 1
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

        if not option.is_available:
            reason = _no_feasible_reason(generated, tested, capped)
            option.unavailable_reason = reason
            option.factual_description = f"Không khả dụng: {reason}"

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