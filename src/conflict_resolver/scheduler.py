from typing import Protocol

from .models import Chunk, ConflictContext, PlanResult


class SchedulerPort(Protocol):
    name: str

    def plan(self, context: ConflictContext) -> PlanResult:
        ...


def free_slots(context: ConflictContext):
    slots = []

    for window in context.active_windows:
        start = max(window.start, context.now_minute)

        if start < window.end:
            slots.append((start, window.end))

    for fixed in context.fixed_tasks:
        blocked_start = fixed.interval.start
        blocked_end = fixed.interval.end

        updated = []

        for start, end in slots:
            if blocked_end <= start or blocked_start >= end:
                updated.append((start, end))
                continue

            if start < blocked_start:
                updated.append((start, blocked_start))

            if blocked_end < end:
                updated.append((blocked_end, end))

        slots = updated

    return sorted(slots)


class ReferenceScheduler:
    name = "reference-first-fit"

    def plan(self, context: ConflictContext) -> PlanResult:
        slots = free_slots(context)

        chunks = []
        unscheduled = {}

        tasks = sorted(
            context.tasks,
            key=lambda task: (
                task.deadline,
                -task.importance,
                task.id,
            ),
        )

        for task in tasks:
            remaining = task.remaining_min

            # Ngoại lệ theo tài liệu:
            # Tổng remaining nhỏ hơn chunk_min được xếp thành một chunk nhỏ.
            minimum = min(task.chunk_min, task.remaining_min)

            for slot_start, slot_end in list(slots):
                if remaining == 0:
                    break

                cursor = max(
                    slot_start,
                    task.earliest_start,
                    context.now_minute,
                )
                limit = min(slot_end, task.deadline)

                while remaining > 0:
                    capacity = limit - cursor - task.buffer_min

                    duration = min(
                        remaining,
                        task.chunk_max,
                        capacity,
                    )

                    # Tránh để lại phần dư nhỏ hơn chunk tối thiểu.
                    if 0 < remaining - duration < minimum:
                        duration = remaining - minimum

                    if duration < minimum:
                        break

                    end = cursor + duration
                    buffer_end = end + task.buffer_min

                    chunks.append(
                        Chunk(
                            task_id=task.id,
                            start=cursor,
                            end=end,
                            buffer_end=buffer_end,
                        )
                    )

                    updated = []

                    for start, finish in slots:
                        if buffer_end <= start or cursor >= finish:
                            updated.append((start, finish))
                            continue

                        if start < cursor:
                            updated.append((start, cursor))

                        if buffer_end < finish:
                            updated.append((buffer_end, finish))

                    slots = updated
                    remaining -= duration
                    cursor = buffer_end

            if remaining > 0:
                unscheduled[task.id] = remaining

        return PlanResult(
            status="NOT_FOUND" if unscheduled else "FEASIBLE",
            chunks=chunks,
            unscheduled=unscheduled,
        )

def tier_of(task):
    """Cấp ưu tiên: bắt buộc luôn cao hơn không bắt buộc."""
    return (3 if task.mandatory else 0) + task.importance - 1


def tier_weights(tasks):
    """Mỗi cấp nặng hơn tổng trọng số của mọi task ở cấp thấp hơn,
    nên một task cấp cao luôn thắng mọi tổ hợp task cấp thấp."""
    counts = {}

    for task in tasks:
        tier = tier_of(task)
        counts[tier] = counts.get(tier, 0) + 1

    weights = {}
    below = 0

    for tier in sorted(counts):
        weights[tier] = below + 1
        below += counts[tier] * weights[tier]

    return weights


class CoreScheduler:
    """Kết nối dữ liệu Conflict với thuật toán CP-SAT."""

    name = "core-cp-sat"

    def __init__(
        self,
        *,
        require_all=True,
        backward=False,
        time_limit=1.0,
    ):
        self.require_all = require_all
        self.backward = backward
        self.time_limit = time_limit
        self.last_status = None

    def _config(self):
        from scheduling_algorithm.core_algorithm.models import Config

        # Đơn vị phút; đã có buffer riêng nên không cộng break mặc định.
        return Config(
            0,
            1440,
            slot_minutes=1,
            break_minutes=0,
            time_limit=self.time_limit,
            objective={"max_priority": 1},
        )

    def _core_tasks(self, context):
        from scheduling_algorithm.core_algorithm.models import Task

        weights = tier_weights(context.tasks)

        # ID UI là chuỗi; core dùng ID số.
        return [
            Task(
                id=index,
                name=task.name,
                duration=task.remaining_min,
                priority=weights[tier_of(task)],
                deadline=task.deadline,
                splittable=True,
                min_chunk=min(
                    task.chunk_min,
                    task.remaining_min,
                ),
                max_chunk=min(
                    task.chunk_max,
                    task.remaining_min,
                ),
                earliest_start=max(
                    context.now_minute,
                    task.earliest_start,
                ),
                buffer_min=task.buffer_min,
            )
            for index, task in enumerate(context.tasks)
        ]

    @staticmethod
    def _hint(context, hint):
        index_of = {
            task.id: index
            for index, task in enumerate(context.tasks)
        }

        pieces = {}

        for chunk in hint or ():
            index = index_of.get(chunk.task_id)

            if index is not None:
                pieces.setdefault(index, []).append(
                    (chunk.start, chunk.end)
                )

        return pieces or None

    def _plan_result(self, context, result):
        chunks = [
            Chunk(
                task_id=context.tasks[index].id,
                start=start,
                end=end,
                buffer_end=(
                    end + context.tasks[index].buffer_min
                ),
            )
            for index, pieces in result.chunks.items()
            for start, end in pieces
        ]

        unscheduled = {
            task.id: task.remaining_min
            for index, task in enumerate(context.tasks)
            if index not in result.chunks
        }

        self.last_status = result.status

        return PlanResult(
            status=(
                "NOT_FOUND"
                if unscheduled
                else "FEASIBLE"
            ),
            chunks=chunks,
            unscheduled=unscheduled,
        )

    def plan(
        self,
        context,
        *,
        compress_id=None,
        compression_min=1,
        required_ids=(),
        hint=(),
    ):
        from scheduling_algorithm.core_algorithm.models import FixedTask
        from scheduling_algorithm.core_algorithm.solve import solve

        # free_slots đã trừ fixed task và thời gian đã qua.
        # Gộp khoảng liền nhau để không tạo ranh giới giả.
        slots = []

        for start, end in free_slots(context):
            if slots and slots[-1][1] == start:
                slots[-1] = (slots[-1][0], end)
            else:
                slots.append((start, end))

        # Phần bù của khoảng trống: giờ ngủ, fixed task, thời gian đã qua.
        blocked = []
        cursor = 0

        for start, end in slots:
            if cursor < start:
                blocked.append((cursor, start))

            cursor = end

        if cursor < 10080:
            blocked.append((cursor, 10080))

        # Core dùng fixed theo từng ngày.
        fixed = []

        for start, end in blocked:
            while start < end:
                day = start // 1440
                stop = min(end, (day + 1) * 1440)

                fixed.append(
                    FixedTask(
                        "blocked",
                        day,
                        start % 1440,
                        stop - day * 1440,
                    )
                )

                start = stop

        compressed_index = next(
            (
                index
                for index, task in enumerate(context.tasks)
                if task.id == compress_id
            ),
            None,
        )

        protected_indices = {
            index
            for index, task in enumerate(context.tasks)
            if task.id in required_ids
        }

        result = solve(
            self._core_tasks(context),
            fixed,
            self._config(),
            require_all=self.require_all,
            backward=self.backward,
            compress_id=compressed_index,
            compression_min=compression_min,
            required_ids=protected_indices,
            hint=self._hint(context, hint),
        )

        return self._plan_result(context, result)

    def plan_relaxed(self, context, blocks, *, step=15):
        """Một lần giải: nới ít nhất để xếp đủ mọi task.

        Trả về (PlanResult, {block_index: (cắt_trái, cắt_phải)}).
        """
        from scheduling_algorithm.core_algorithm.solve import solve

        result = solve(
            self._core_tasks(context),
            [],
            self._config(),
            require_all=True,
            elastic=blocks,
            step=step,
        )

        return self._plan_result(context, result), result.elastic