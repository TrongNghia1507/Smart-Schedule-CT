"""Tìm thời lượng LỚN NHẤT của target khi giảm thời lượng (Lựa chọn 2).

1. Chặn trên U theo sức chứa (tức thì, chắc chắn).
2. Thử đúng U: đặt target vào chỗ trống, khoá lại, xếp các task còn lại.
   Được => tối ưu đã chứng minh.
3. Không được: chặt nhị phân, rồi hỏi mô hình đầy đủ "có mức nào trong (D, U]?".
"""

import os
import time
from dataclasses import dataclass

from .models import Chunk, FixedTask, Interval, PlanResult
from .scheduler import CoreScheduler, ReferenceScheduler, free_slots

DAY = 1440


@dataclass
class CompressionOutcome:
    duration: int | None      # thời lượng lớn nhất tìm được (None: không có)
    proven: bool              # True: chắc chắn không có mức nào lớn hơn
    plan: PlanResult | None   # lịch đầy đủ (mọi task) ứng với `duration`
    upper_bound: int          # chặn trên đã tính
    timed_out: bool = False   # có bước nào bị solver bỏ dở vì hết giờ


def _ceil_div(a, b):
    return -(-a // b)


def _with_duration(context, target_id, minutes):
    candidate = context.model_copy(deep=True)

    for task in candidate.tasks:
        if task.id == target_id:
            task.remaining_min = minutes

    return candidate


def _segments(context, target, unit, split_midnight):
    """Các đoạn trống liên tục target dùng được, cắt theo
    [max(now, earliest_start), deadline], căn theo `unit`."""
    low = max(context.now_minute, target.earliest_start)
    high = target.deadline // unit * unit

    merged = []

    for start, end in free_slots(context):
        start, end = max(start, low), min(end, high)

        if start >= end:
            continue

        if merged and merged[-1][1] == start:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))

    result = []

    for start, end in merged:
        pieces = [(start, end)]

        if split_midnight:
            pieces = []
            cursor = start

            while cursor < end:
                stop = min(end, (cursor // DAY + 1) * DAY)
                pieces.append((cursor, stop))
                cursor = stop

        for a, b in pieces:
            a = _ceil_div(a, unit) * unit
            b = b // unit * unit

            if a < b:
                result.append((a, b))

    return result


def _segment_capacity(length, task, unit):
    """Lượng việc tối đa trong một đoạn trống liên tục dài `length` phút:
    mỗi chunk <= chunk_max và kèm buffer phía sau."""
    buffer = task.buffer_min

    if length <= buffer:
        return 0

    pieces = _ceil_div(length, task.chunk_max + buffer)

    return max(0, (length - pieces * buffer) // unit * unit)


def upper_bound(context, target, unit):
    """Chặn trên CHẮC CHẮN của thời lượng target (đã trừ 1 vì phải GIẢM)."""
    segments = _segments(context, target, unit, split_midnight=False)
    capacities = [
        _segment_capacity(end - start, target, unit)
        for start, end in segments
    ]

    usable = sum(c for c in capacities if c >= target.chunk_min)

    if usable >= target.chunk_min:
        bound = usable
    else:
        bound = min(
            max(capacities, default=0),
            target.chunk_min - unit,
        )

    bound = min(bound, (target.remaining_min - 1) // unit * unit)

    def impossible(minutes):
        return CoreScheduler.provably_infeasible(
            _with_duration(context, target.id, minutes)
        )

    low, high = 0, bound // unit

    while low < high:
        mid = (low + high + 1) // 2

        if impossible(mid * unit):
            high = mid - 1
        else:
            low = mid

    return max(0, low * unit)


def _split_into_chunks(amount, task, minimum, unit):
    pieces = _ceil_div(amount, task.chunk_max)

    if amount < pieces * minimum:
        return None

    units = amount // unit
    base, extra = divmod(units, pieces)

    return [
        (base + (1 if index < extra else 0)) * unit
        for index in range(pieces)
    ]


def _layout(segments, duration, task, unit):
    """Đặt `duration` phút của target vào các đoạn trống (xếp chặt từ đầu
    mỗi đoạn). Trả về list[Chunk] hoặc None."""
    minimum = min(task.chunk_min, duration)
    remaining = duration
    chunks = []

    for start, end in segments:
        if remaining <= 0:
            break

        capacity = _segment_capacity(end - start, task, unit)
        take = min(remaining, capacity)

        if 0 < remaining - take < minimum:
            take = remaining - minimum

        parts = None

        while take >= minimum and take > 0:
            parts = _split_into_chunks(take, task, minimum, unit)

            if parts:
                break

            take -= unit

        if not parts:
            continue

        cursor = start

        for length in parts:
            chunks.append(
                Chunk(
                    task_id=task.id,
                    start=cursor,
                    end=cursor + length,
                    buffer_end=cursor + length + task.buffer_min,
                )
            )
            cursor += length + task.buffer_min

        remaining -= take

    return chunks if remaining == 0 else None


def validate_plan(context, plan):
    """Kiểm tra độc lập một lịch có đúng MỌI ràng buộc không."""
    slots = free_slots(context)
    tasks = {task.id: task for task in context.tasks}
    totals = {}
    busy = []

    for chunk in plan.chunks:
        task = tasks.get(chunk.task_id)

        if task is None:
            return False

        length = chunk.end - chunk.start

        if (
            length <= 0
            or length > task.chunk_max
            or length < min(task.chunk_min, task.remaining_min)
            or chunk.buffer_end != chunk.end + task.buffer_min
            or chunk.start < max(task.earliest_start, context.now_minute)
            or chunk.buffer_end > task.deadline
            or not any(
                start <= chunk.start and chunk.buffer_end <= end
                for start, end in slots
            )
        ):
            return False

        totals[task.id] = totals.get(task.id, 0) + length
        busy.append((chunk.start, chunk.buffer_end))

    if any(
        totals.get(task.id, 0) != task.remaining_min
        for task in context.tasks
    ):
        return False

    busy.sort()

    return all(
        previous[1] <= current[0]
        for previous, current in zip(busy, busy[1:])
    )


def _fit_others(context, target, chunks, time_limit):
    """Khoá chỗ của target rồi xếp các task còn lại.
    Trả về (PlanResult đầy đủ | None, timed_out). time_limit <= 0: chỉ first-fit."""
    reduced = context.model_copy(deep=True)
    reduced.tasks = [
        task for task in reduced.tasks if task.id != target.id
    ]

    if not reduced.tasks:
        return (
            PlanResult(
                status="FEASIBLE",
                chunks=list(chunks),
                unscheduled={},
                solver_status="OPTIMAL",
            ),
            False,
        )

    for index, chunk in enumerate(chunks):
        reduced.fixed_tasks.append(
            FixedTask(
                id=f"__target_{index}",
                name=target.name,
                interval=Interval(start=chunk.start, end=chunk.buffer_end),
            )
        )

    def combine(result):
        return PlanResult(
            status="FEASIBLE",
            chunks=[*result.chunks, *chunks],
            unscheduled={},
            solver_status=result.solver_status,
        )

    quick = ReferenceScheduler().plan(reduced)

    if quick.status == "FEASIBLE" and validate_plan(reduced, quick):
        return combine(quick), False

    if time_limit <= 0:
        return None, False

    result = CoreScheduler(time_limit=time_limit).plan(reduced)

    if result.status != "FEASIBLE":
        return None, result.status == "UNKNOWN"

    return combine(result), False


DEFAULT_BUDGET = 30.0


def default_budget():
    """Tổng thời gian tối đa (giây). Đổi bằng biến môi trường
    COMPRESSION_TIME_BUDGET nếu máy chậm."""
    try:
        return float(os.environ["COMPRESSION_TIME_BUDGET"])
    except (KeyError, ValueError):
        return DEFAULT_BUDGET


def find_max_duration(context, target, *, time_limit=3.0, budget=None):
    """Thời lượng lớn nhất của target mà MỌI task khác vẫn xếp đủ."""
    budget = default_budget() if budget is None else budget
    started = time.monotonic()

    def left():
        return budget - (time.monotonic() - started)

    unit = CoreScheduler._slot_minutes(context)
    bound = upper_bound(context, target, unit)

    if bound < unit:
        return CompressionOutcome(None, True, None, bound)

    segments = _segments(context, target, unit, split_midnight=True)
    orders = (segments[::-1], segments)   # ưu tiên đoạn muộn, rồi đoạn sớm
    timed_out = False

    def attempt(duration, limit):
        nonlocal timed_out

        layouts = [
            chunks
            for chunks in (
                _layout(ordered, duration, target, unit)
                for ordered in orders
            )
            if chunks is not None
        ]

        for chunks in layouts:
            plan, _ = _fit_others(context, target, chunks, 0)

            if plan is not None:
                return plan

        if limit > 0 and layouts:
            plan, stuck = _fit_others(context, target, layouts[0], limit)
            timed_out = timed_out or stuck
            return plan

        return None

    # Bước 1: đúng chặn trên. Khả thi => tối ưu đã chứng minh.
    plan = attempt(bound, max(0.0, left() * 0.6))

    if plan is not None:
        return CompressionOutcome(bound, True, plan, bound, timed_out)

    # Bước 2: chặt nhị phân các mức thấp hơn.
    low, high = 1, bound // unit - 1
    found, found_plan = None, None

    while low <= high and left() > 0:
        mid = (low + high) // 2
        limit = max(1.0, min(time_limit, left() / 8))
        plan = attempt(mid * unit, limit)

        if plan is not None:
            found, found_plan = mid * unit, plan
            low = mid + 1
        else:
            high = mid - 1

    # Bước 3: hỏi mô hình đầy đủ "có mức nào lớn hơn không?".
    start = (found or 0) + unit
    proven = False

    if start > bound:
        proven = True
    elif left() >= 3:
        engine = CoreScheduler(time_limit=left() - 1)
        result = engine.plan(
            context,
            compress_id=target.id,
            compression_min=start,
            compression_max=bound,
            hint=found_plan.chunks if found_plan else (),
        )

        if result.status == "FEASIBLE":
            duration = sum(
                chunk.end - chunk.start
                for chunk in result.chunks
                if chunk.task_id == target.id
            )

            return CompressionOutcome(
                duration,
                engine.last_status == "OPTIMAL",
                result,
                bound,
                timed_out,
            )

        if result.status == "UNKNOWN":
            timed_out = True
        else:
            proven = True
    else:
        timed_out = True

    return CompressionOutcome(found, proven, found_plan, bound, timed_out)