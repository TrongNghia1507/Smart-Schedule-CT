from ..models import WEEK


def exclude_candidates(context, target):
    if not target.allow_exclude:
        return

    candidate = context.model_copy(deep=True)
    candidate.tasks = [
        task for task in candidate.tasks
        if task.id != target.id
    ]

    yield (
        candidate,
        {
            "operation": "EXCLUDE_FROM_WEEK",
            "task_id": target.id,
        },
        f"Bỏ task “{target.name}” khỏi kế hoạch tuần hiện tại.",
        ["Task vẫn được lưu và chưa được xem là hoàn thành."],
    )


def compress_candidates(context, target):
    if not target.allow_compress:
        return

    step = context.policy.compression_step_minutes

    values = list(
        range(
            target.remaining_min - step,
            target.min_remaining_min - 1,
            -step,
        )
    )

    if target.min_remaining_min < target.remaining_min:
        values.append(target.min_remaining_min)

    for duration in dict.fromkeys(values):
        candidate = context.model_copy(deep=True)

        task = next(
            task for task in candidate.tasks
            if task.id == target.id
        )
        task.remaining_min = duration

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
            },
            (
                f"Giảm thời lượng task “{target.name}” từ "
                f"{target.remaining_min} xuống {duration} phút."
            ),
            [
                "Giảm thời lượng không bảo đảm hoàn thành "
                "đủ phạm vi công việc ban đầu."
            ],
        )


def postpone_candidates(context, target):
    if target.kind == "soft":
        movable = [target]
    else:
        movable = sorted(
            (
                task for task in context.tasks
                if task.id != target.id
                and task.kind == "soft"
                and task.importance < target.importance
            ),
            key=lambda task: (task.importance, task.id),
        )

    for original in movable:
        if original.max_postpone_minutes <= 0:
            continue

        latest = min(
            WEEK,
            original.deadline + original.max_postpone_minutes,
        )

        deadlines = list(
            range(original.deadline + 1440, latest + 1, 1440)
        )

        if latest > original.deadline:
            deadlines.append(latest)

        for deadline in sorted(set(deadlines)):
            candidate = context.model_copy(deep=True)

            task = next(
                task for task in candidate.tasks
                if task.id == original.id
            )
            task.deadline = deadline

            yield (
                candidate,
                {
                    "operation": "POSTPONE_TASK",
                    "task_id": original.id,
                    "old_deadline": original.deadline,
                    "new_deadline": deadline,
                },
                (
                    f"Dời deadline task “{original.name}” từ phút "
                    f"{original.deadline} sang phút {deadline} của tuần."
                ),
                ["Phương án chỉ được kiểm chứng trong tuần hiện tại."],
            )


def _relax_inputs(context, target):
    eligible = [
        fixed for fixed in context.fixed_tasks
        if fixed.can_shorten
        and fixed.importance < target.importance
        and fixed.interval.start >= context.now_minute
        and fixed.interval.start < target.deadline
        and fixed.interval.end - fixed.interval.start > fixed.min_duration
    ]

    fixed_groups = [[fixed] for fixed in eligible]

    if len(eligible) > 1:
        fixed_groups.append(eligible)

    # None: thử không mở rộng khung giờ.
    expansions = [None]

    for index, window in enumerate(context.active_windows):
        if (
            window.start >= target.deadline
            or window.end <= context.now_minute
        ):
            continue

        day_start = (window.start // 1440) * 1440
        day_end = ((window.end - 1) // 1440 + 1) * 1440

        previous_end = max(
            (
                item.end for item in context.active_windows
                if item.end <= window.start
            ),
            default=0,
        )
        next_start = min(
            (
                item.start for item in context.active_windows
                if item.start >= window.end
            ),
            default=WEEK,
        )

        start = max(
            day_start,
            previous_end,
            context.now_minute,
            window.start - context.policy.max_earlier_minutes,
        )
        start = min(start, window.start)

        end = min(
            day_end,
            next_start,
            window.end + context.policy.max_later_minutes,
        )

        if start != window.start or end != window.end:
            expansions.append((index, start, end))

    return eligible, fixed_groups, expansions


def relax_candidates(context, target):
    eligible, fixed_groups, expansions = _relax_inputs(context, target)

    # Thử từng nhóm fixed, mở rộng giờ, và kết hợp cả hai.
    for group in [[], *fixed_groups]:
        for expansion in expansions:
            if not group and expansion is None:
                continue

            candidate = context.model_copy(deep=True)
            changes = []
            descriptions = []

            for original in group:
                fixed = next(
                    item for item in candidate.fixed_tasks
                    if item.id == original.id
                )

                old_end = fixed.interval.end
                fixed.interval.end = (
                    fixed.interval.start + fixed.min_duration
                )

                reduced = old_end - fixed.interval.end

                changes.append({
                    "operation": "SHORTEN_FIXED",
                    "task_id": fixed.id,
                    "old_end": old_end,
                    "new_end": fixed.interval.end,
                })

                descriptions.append(
                    f"Rút ngắn việc cố định “{fixed.name}” {reduced} phút."
                )

            if expansion is not None:
                index, start, end = expansion
                window = candidate.active_windows[index]
                window.start = start
                window.end = end

                changes.append({
                    "operation": "EXPAND_ACTIVE_WINDOW",
                    "window_index": index,
                    "new_start": start,
                    "new_end": end,
                })

                descriptions.append(
                    f"Đổi khung hoạt động số {index} "
                    f"thành [{start}, {end})."
                )

            yield (
                candidate,
                {"changes": changes},
                " ".join(descriptions),
                [
                    "Chỉ áp dụng sau khi người dùng xác nhận "
                    "các thay đổi sinh hoạt."
                ],
            )


# ---------------------------------------------------------------------------
# Kiểm tra ngữ cảnh: option chỉ "khả dụng" khi đúng bản chất của chính nó.
# Mỗi hàm trả về None (có thể thử sinh ứng viên) hoặc lý do cụ thể, đọc được
# bởi người dùng, giải thích vì sao option này không áp dụng được ở ngữ cảnh này.
# ---------------------------------------------------------------------------

def exclude_precheck(context, target):
    if not target.allow_exclude:
        return (
            f"Task “{target.name}” không cho phép gỡ khỏi kế hoạch tuần "
            "(allow_exclude = false)."
        )
    return None


def compress_precheck(context, target):
    if not target.allow_compress:
        return (
            f"Task “{target.name}” không cho phép rút gọn thời lượng "
            "(allow_compress = false)."
        )

    if target.min_remaining_min >= target.remaining_min:
        return (
            f"Thời lượng task “{target.name}” ({target.remaining_min} phút) "
            "đã bằng mức tối thiểu cho phép nên không còn chỗ để rút gọn."
        )

    return None


def postpone_precheck(context, target):
    if target.kind == "soft":
        if target.max_postpone_minutes <= 0:
            return (
                f"Task soft “{target.name}” không cho phép dời hạn chót "
                "(max_postpone_minutes = 0)."
            )

        if target.deadline >= WEEK:
            return (
                f"Hạn chót của task “{target.name}” đã ở cuối tuần; engine chỉ "
                "kiểm chứng trong tuần hiện tại nên không dời thêm được."
            )

        return None

    # Task hard/asap không tự dời hạn; chỉ dời task soft quan trọng thấp hơn.
    movable = [
        task for task in context.tasks
        if task.id != target.id
        and task.kind == "soft"
        and task.importance < target.importance
    ]

    if not movable:
        return (
            f"Task “{target.name}” thuộc loại {target.kind} nên không tự dời hạn, "
            f"và không có task soft nào có độ quan trọng thấp hơn "
            f"{target.importance} để dời thay."
        )

    if all(
        task.max_postpone_minutes <= 0 or task.deadline >= WEEK
        for task in movable
    ):
        return (
            "Các task soft có độ quan trọng thấp hơn đều không cho phép dời "
            "hạn chót hoặc đã sát cuối tuần."
        )

    return None


def relax_precheck(context, target):
    eligible, _, expansions = _relax_inputs(context, target)

    if eligible or len(expansions) > 1:
        return None

    return (
        "Không có việc cố định nào được phép rút ngắn với độ quan trọng "
        f"thấp hơn {target.importance} trước hạn chót, và chính sách khung "
        "giờ hiện tại không cho mở rộng thời gian hoạt động."
    )
