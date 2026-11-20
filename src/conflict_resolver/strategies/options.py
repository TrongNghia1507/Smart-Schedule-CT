from ..models import WEEK
from ..scheduler import free_slots


def exclude_candidates(context, target):
    # Quyền bỏ task do người dùng quyết định (allow_exclude), kể cả với
    # task bắt buộc. Option chỉ là đề xuất; không bao giờ tự áp dụng.
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
            "was_mandatory": target.mandatory,
        },
        f"Bỏ {target.name} khỏi lịch tuần.",
        [
            "Chưa đánh dấu task là hoàn thành.",
            *(
                [
                    "Đây là task bắt buộc: chỉ bỏ khi bạn "
                    "chủ động chọn phương án này."
                ]
                if target.mandatory
                else []
            ),
        ],
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



def _occurrence_groups(context):
    """Gom các mảnh của cùng một lần diễn ra: {khóa: [FixedTask, ...]}."""
    groups = {}

    for fixed in context.fixed_tasks:
        groups.setdefault(fixed.group or fixed.id, []).append(fixed)

    return groups


def _removable(pieces, context, target):
    """Một lần diễn ra có xóa được để nhường chỗ cho target không.

    Chỉ xét sự kiện đã được đánh dấu "xóa được khi bận", chưa bắt đầu,
    và nằm trước deadline của target (ngày deadline và các ngày trước đó).
    """
    if not all(piece.can_remove for piece in pieces):
        return False

    mains = [piece for piece in pieces if not piece.ancillary] or pieces

    start = min(piece.interval.start for piece in mains)
    end = max(piece.interval.end for piece in mains)

    return (
        start >= context.now_minute
        and start < target.deadline
        and end > target.earliest_start
    )


def _window_room(context, target, index):
    """Mức nới tối đa của một khung giờ thức: (sớm hơn, muộn hơn).

    Chỉ nới các ngày không sau ngày deadline. Ở ngày deadline, không
    nới quá giờ deadline vì phần đó không giúp ích gì cho target.
    """
    policy = context.policy
    now = context.now_minute
    windows = context.active_windows
    window = windows[index]

    # Deadline đúng 00:00 thuộc ngày trước đó.
    deadline_day = (target.deadline - 1) // 1440
    day = window.start // 1440

    if day > deadline_day:
        return 0, 0

    previous_end = max(
        (
            other.end
            for other_index, other in enumerate(windows)
            if other_index != index and other.end <= window.start
        ),
        default=0,
    )

    next_start = min(
        (
            other.start
            for other_index, other in enumerate(windows)
            if other_index != index and other.start >= window.end
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

        if day == deadline_day:
            upper = min(upper, target.deadline)

        later = max(0, upper - window.end)

    return earlier, later


def relax_candidates(context, target):
    """Phương án dự phòng (ReferenceScheduler), nới từng bước.

    Giai đoạn 1: xóa các sự kiện "xóa được khi bận", gần deadline trước.
    Giai đoạn 2: nới giờ thức/ngủ từ sát deadline lùi dần:
      - ngày deadline: chỉ dậy sớm hơn (và thức muộn hơn nếu deadline
        còn sau giờ ngủ);
      - các ngày trước: thức khuya hơn và dậy sớm hơn.
    Mỗi lần thêm một thay đổi là một đề xuất; resolve() chọn đề xuất đầu
    tiên mà engine xếp được đủ.
    """
    candidate = context.model_copy(deep=True)
    changes = []

    def proposal():
        return (
            candidate.model_copy(deep=True),
            {
                "changes": [dict(change) for change in changes],
            },
            (
                "Xóa các sự kiện đã cho phép xóa khi bận, rồi nới giờ "
                "thức/ngủ từ sát deadline lùi dần."
            ),
            [
                "Cần người dùng chọn trước khi "
                "đổi giờ sinh hoạt hoặc xóa sự kiện."
            ],
        )

    # Giai đoạn 1: xóa sự kiện, từ sát deadline trở về trước.
    groups = _occurrence_groups(context)

    eligible = sorted(
        (
            (key, pieces)
            for key, pieces in groups.items()
            if _removable(pieces, context, target)
        ),
        key=lambda item: -min(
            piece.interval.start for piece in item[1]
        ),
    )

    for key, pieces in eligible:
        candidate.fixed_tasks = [
            fixed
            for fixed in candidate.fixed_tasks
            if (fixed.group or fixed.id) != key
        ]

        changes.append(remove_change(key, pieces))

        yield proposal()

    # Giai đoạn 2: nới giờ thức/ngủ từ ngày deadline lùi dần.
    deadline_day = (target.deadline - 1) // 1440

    for day in range(deadline_day, -1, -1):
        indices = sorted(
            range(len(candidate.active_windows)),
            key=lambda index: candidate.active_windows[index].start,
        )

        for index in indices:
            window = candidate.active_windows[index]

            if window.start // 1440 != day:
                continue

            if window.end <= context.now_minute:
                continue

            earlier, later = _window_room(candidate, target, index)

            if earlier == 0 and later == 0:
                continue

            window.start -= earlier
            window.end += later

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

        if (
            changes
            and changes[-1]["operation"] == "EXPAND_ACTIVE_WINDOW"
        ):
            yield proposal()


def remove_change(key, pieces):
    """Mô tả việc xóa một lần diễn ra (gồm cả mảnh chuẩn bị/đi về)."""
    mains = [piece for piece in pieces if not piece.ancillary] or pieces
    main = min(mains, key=lambda piece: piece.interval.start)

    return {
        "operation": "REMOVE_FIXED",
        "group": key,
        "name": main.name,
        "task_ids": [piece.id for piece in pieces],
        "start": main.interval.start,
        "end": max(piece.interval.end for piece in mains),
        "removed_minutes": sum(
            piece.interval.end - piece.interval.start
            for piece in pieces
        ),
    }


def relaxation_blocks(context, target):
    """Dựng khoảng bị chặn cho option 3 (CoreScheduler).

    Trả về (blocks, sources). sources[i] mô tả blocks[i]:
      ("fixed", task_id)               một mảnh sự kiện cố định (có thể bị xóa)
      ("gap", window_trước, window_sau) khoảng ngủ giữa hai cửa sổ thức
      ("static",)                      phần đã qua, không đổi được

    Hai cách nới:
      1. XÓA hẳn các lần diễn ra "xóa được khi bận" (không rút ngắn).
      2. Nới giờ thức/ngủ; giá mỗi phút tăng theo số ngày cách ngày
         deadline, nên solver nới sát deadline trước.
    """
    from scheduling_algorithm.core_algorithm.models import ElasticBlock

    policy = context.policy
    now = context.now_minute
    windows = context.active_windows

    # Deadline đúng 00:00 thuộc ngày trước đó.
    deadline_day = (target.deadline - 1) // 1440

    blocks = []
    sources = []

    # 1. Sự kiện cố định: hoặc giữ nguyên, hoặc xóa cả lần diễn ra.
    removable_keys = {
        key
        for key, pieces in _occurrence_groups(context).items()
        if _removable(pieces, context, target)
    }

    for fixed in context.fixed_tasks:
        start = fixed.interval.start
        end = fixed.interval.end

        if end <= now:
            continue

        key = fixed.group or fixed.id

        blocks.append(
            ElasticBlock(
                start,
                end,
                0,
                0,
                touch=policy.event_touch_penalty,
                group="event",
                removable=key if key in removable_keys else None,
                remove_price=policy.remove_cost_per_minute,
            )
        )
        sources.append(("fixed", fixed.id))

    # 2. Mức nới tối đa của từng cửa sổ thức (sớm hơn, muộn hơn).
    bounds = {
        index: _window_room(context, target, index)
        for index in range(len(windows))
    }

    def tier_price(index):
        """Giá mỗi phút nới cửa sổ `index`: càng xa deadline càng đắt."""
        tier = max(0, deadline_day - windows[index].start // 1440)

        return (
            policy.sleep_cost_per_minute
            + policy.sleep_tier_step_cost * tier
        )

    # 3. Giờ ngủ = khoảng ngoài các cửa sổ thức.
    #    Nới cửa sổ trước (thức khuya hơn)  = đẩy đầu trái khoảng ngủ sang phải,
    #    nới cửa sổ sau   (dậy sớm hơn)     = kéo đầu phải khoảng ngủ sang trái.
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
                left_price=(
                    tier_price(before) if before is not None else None
                ),
                right_price=(
                    tier_price(after) if after is not None else None
                ),
                touch=policy.event_touch_penalty,
                group="gap",
            )
        )
        sources.append(("gap", before, after))

    return blocks, sources
