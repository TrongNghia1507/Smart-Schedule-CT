from ..models import WEEK
from ..scheduler import free_slots


def exclude_candidates(context, target):
    if target.mandatory or not target.allow_exclude:
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
def relaxation_blocks(context, target):
    """Dựng khoảng bị chặn co được cho option 3 (CoreScheduler).

    Trả về (blocks, sources). sources[i] mô tả blocks[i]:
      ("fixed", task_id)               rút đuôi một sự kiện cố định
      ("gap", window_trước, window_sau) khoảng ngủ giữa hai cửa sổ thức
      ("static",)                      phần đã qua, không đổi được
    """
    from scheduling_algorithm.core_algorithm.models import ElasticBlock

    policy = context.policy
    now = context.now_minute
    windows = context.active_windows

    # Deadline đúng 00:00 thuộc ngày trước đó.
    deadline_day = (target.deadline - 1) // 1440

    blocks = []
    sources = []

    # 1. Sự kiện cố định: giữ start, chỉ rút end về tối thiểu min_duration.
    for fixed in context.fixed_tasks:
        start = fixed.interval.start
        end = fixed.interval.end

        if end <= now:
            continue

        eligible = (
            fixed.can_shorten
            and start >= now
            and start < target.deadline
            and end > target.earliest_start
        )

        cut_max = (
            end - start - fixed.min_duration
            if eligible
            else 0
        )

        blocks.append(
            ElasticBlock(
                start,
                end,
                0,
                max(0, cut_max),
                price=policy.fixed_cut_cost_per_minute,
                touch=policy.event_touch_penalty,
                group="event",
            )
        )
        sources.append(("fixed", fixed.id))

    # 2. Mức nới tối đa của từng cửa sổ thức (sớm hơn, muộn hơn).
    def limits(index):
        window = windows[index]
        day = window.start // 1440

        if day > deadline_day:
            return 0, 0

        previous_end = max(
            (
                other.end
                for other_index, other in enumerate(windows)
                if other_index != index
                and other.end <= window.start
            ),
            default=0,
        )

        next_start = min(
            (
                other.start
                for other_index, other in enumerate(windows)
                if other_index != index
                and other.start >= window.end
            ),
            default=WEEK,
        )

        lower = max(
            day * 1440,
            previous_end,
            now,
            window.start - policy.max_earlier_minutes,
        )

        earlier = max(0, window.start - lower)

        if window.end <= now:
            later = 0
        else:
            upper = min(
                (day + 1) * 1440,
                next_start,
                window.end + policy.max_later_minutes,
            )
            later = max(0, upper - window.end)

        return earlier, later

    bounds = {index: limits(index) for index in range(len(windows))}

    # 3. Giờ ngủ = khoảng ngoài các cửa sổ thức.
    #    Nới cửa sổ trước = đẩy đầu trái khoảng ngủ sang phải,
    #    nới cửa sổ sau   = kéo đầu phải khoảng ngủ sang trái.
    order = sorted(
        range(len(windows)),
        key=lambda index: windows[index].start,
    )

    spans = []
    cursor = 0
    previous = None

    for index in order:
        spans.append((cursor, windows[index].start, previous, index))
        cursor = windows[index].end
        previous = index

    spans.append((cursor, WEEK, previous, None))

    if now > 0:
        blocks.append(ElasticBlock(0, now, group="gap"))
        sources.append(("static",))

    for gap_start, gap_end, before, after in spans:
        start = max(gap_start, now)

        if start >= gap_end:
            continue

        length = gap_end - start

        left_max = bounds[before][1] if before is not None else 0
        right_max = bounds[after][0] if after is not None else 0

        if gap_start < now:
            left_max = 0

        blocks.append(
            ElasticBlock(
                start,
                gap_end,
                min(left_max, length),
                min(right_max, length),
                price=policy.sleep_cost_per_minute,
                touch=policy.event_touch_penalty,
                group="gap",
            )
        )
        sources.append(("gap", before, after))

    return blocks, sources

