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
        f"Bỏ task {target.id} khỏi kế hoạch tuần hiện tại.",
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
                f"Giảm thời lượng task {target.id} từ "
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
                    f"Dời deadline task {original.id} từ phút "
                    f"{original.deadline} sang phút {deadline} của tuần."
                ),
                ["Phương án chỉ được kiểm chứng trong tuần hiện tại."],
            )


def relax_candidates(context, target):
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
                    f"Rút ngắn fixed task {fixed.id} {reduced} phút."
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