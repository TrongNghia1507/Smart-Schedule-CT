from ..models import WEEK
from ..scheduler import free_slots


def exclude_candidates(context, target):
    if not target.allow_exclude:
        return

    candidate = context.model_copy(deep=True)

    candidate.tasks = [
        task
        for task in candidate.tasks
        if task.id != target.id
    ]

    yield (
        candidate,
        {
            "operation": "EXCLUDE_FROM_WEEK",
            "task_id": target.id,
        },
        f"Bỏ {target.name} khỏi lịch tuần.",
        ["Chưa đánh dấu task là hoàn thành."],
    )


def compress_candidates(context, target):
    """Dự phòng cho ReferenceScheduler.

    Luồng CoreScheduler dùng phép tối ưu trực tiếp
    trong optimized_compression của resolver.py.
    """
    if not target.allow_compress:
        return

    capacity = sum(
        max(
            0,
            min(end, target.deadline)
            - max(start, target.earliest_start),
        )
        for start, end in free_slots(context)
    )

    upper = min(
        target.remaining_min - 1,
        capacity,
    )

    for duration in range(
        upper,
        target.min_remaining_min - 1,
        -1,
    ):
        candidate = context.model_copy(deep=True)

        task = next(
            task
            for task in candidate.tasks
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
                f"Giảm {target.name}: "
                f"{target.remaining_min} → {duration} phút."
            ),
            [
                "Giảm thời lượng có thể làm giảm "
                "phạm vi công việc."
            ],
        )


def postpone_candidates(context, target):
    # Chỉ dời deadline của chính soft task đang xử lý.
    if target.kind != "soft":
        return

    if target.max_postpone_minutes <= 0:
        return

    latest = min(
        WEEK,
        target.deadline + target.max_postpone_minutes,
    )

    slots = free_slots(context)

    for deadline in range(
        target.deadline + 1,
        latest + 1,
    ):
        # Chỉ là kiểm tra điều kiện cần.
        # Chunk, buffer và task cạnh tranh vẫn do core kiểm tra.
        capacity = sum(
            max(
                0,
                min(end, deadline)
                - max(start, target.earliest_start),
            )
            for start, end in slots
        )

        if capacity < target.remaining_min:
            continue

        candidate = context.model_copy(deep=True)

        task = next(
            task
            for task in candidate.tasks
            if task.id == target.id
        )

        task.deadline = deadline

        yield (
            candidate,
            {
                "operation": "POSTPONE_TASK",
                "task_id": target.id,
                "old_deadline": target.deadline,
                "new_deadline": deadline,
            },
            (
                f"Dời deadline {target.name} "
                f"đến phút {deadline} của tuần."
            ),
            [
                "Chỉ tìm trong tuần hiện tại; "
                "không tự dời hard/asap."
            ],
        )


def relax_candidates(context, target):
    candidate = context.model_copy(deep=True)
    changes = []

    eligible = sorted(
        (
            fixed
            for fixed in candidate.fixed_tasks
            if fixed.can_shorten
            and fixed.interval.start >= context.now_minute
            and fixed.interval.start < target.deadline
            and fixed.interval.end > target.earliest_start
            and (
                fixed.interval.end - fixed.interval.start
                > fixed.min_duration
            )
        ),
        key=lambda fixed: (
            -fixed.interval.start,
            fixed.id,
        ),
    )

    def proposal():
        return (
            candidate.model_copy(deep=True),
            {
                "changes": [
                    dict(change)
                    for change in changes
                ]
            },
            (
                "Rút fixed về min_duration trước, "
                "rồi mở giờ thức từ ngày deadline lùi dần."
            ),
            [
                "Cần người dùng chọn trước khi "
                "đổi giờ sinh hoạt."
            ],
        )

    # Giai đoạn 1: rút fixed, thay đổi được cộng dồn.
    for fixed in eligible:
        old_end = fixed.interval.end

        fixed.interval.end = (
            fixed.interval.start
            + fixed.min_duration
        )

        changes.append(
            {
                "operation": "SHORTEN_FIXED",
                "task_id": fixed.id,
                "old_end": old_end,
                "new_end": fixed.interval.end,
            }
        )

        yield proposal()

    # Deadline đúng 00:00 thuộc ngày trước đó.
    deadline_day = (target.deadline - 1) // 1440

    # Giai đoạn 2: nới giờ thức cộng dồn từng ngày.
    for day in range(deadline_day, -1, -1):
        indices = sorted(
            range(len(candidate.active_windows)),
            key=lambda index: (
                candidate.active_windows[index].start
            ),
        )

        for index in indices:
            window = candidate.active_windows[index]

            if window.start // 1440 != day:
                continue

            if window.end <= context.now_minute:
                continue

            previous_end = max(
                (
                    item.end
                    for other_index, item
                    in enumerate(candidate.active_windows)
                    if other_index != index
                    and item.end <= window.start
                ),
                default=0,
            )

            next_start = min(
                (
                    item.start
                    for other_index, item
                    in enumerate(candidate.active_windows)
                    if other_index != index
                    and item.start >= window.end
                ),
                default=WEEK,
            )

            start = max(
                day * 1440,
                previous_end,
                context.now_minute,
                (
                    window.start
                    - context.policy.max_earlier_minutes
                ),
            )

            start = min(start, window.start)

            end = min(
                (day + 1) * 1440,
                next_start,
                (
                    window.end
                    + context.policy.max_later_minutes
                ),
            )

            if (start, end) == (
                window.start,
                window.end,
            ):
                continue

            window.start = start
            window.end = end

            changes.append(
                {
                    "operation": "EXPAND_ACTIVE_WINDOW",
                    "window_index": index,
                    "new_start": start,
                    "new_end": end,
                }
            )

        if (
            changes
            and changes[-1]["operation"]
            == "EXPAND_ACTIVE_WINDOW"
        ):
            yield proposal()