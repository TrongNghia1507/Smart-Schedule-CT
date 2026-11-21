from typing import Protocol

from .models import Chunk, ConflictContext, PlanResult

INCONCLUSIVE = {"UNKNOWN", "MODEL_INVALID"}
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

    @staticmethod
    def _slot_minutes(context):
        """5 phút nếu MỌI mốc thời gian chia hết cho 5, ngược lại 1 phút."""
        values = [context.now_minute]

        for task in context.tasks:
            values += [
                task.remaining_min,
                task.earliest_start,
                task.chunk_min,
                task.chunk_max,
                task.buffer_min,
            ]

        for fixed in context.fixed_tasks:
            values += [fixed.interval.start, fixed.interval.end]

        for window in context.active_windows:
            values += [window.start, window.end]

        return 5 if all(value % 5 == 0 for value in values) else 1

    def _config(self, slot_minutes=1):
        from scheduling_algorithm.core_algorithm.models import Config

        return Config(
            0,
            1440,
            slot_minutes=slot_minutes,
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

    def _plan_result(self, context, result, slot_minutes=1):
        self.last_status = result.status
        if result.status in INCONCLUSIVE:
            return PlanResult(
                status="UNKNOWN",
                chunks=[],
                unscheduled={},
                solver_status=result.status,
            )
        chunks = [
            Chunk(
                task_id=context.tasks[index].id,
                start=start * slot_minutes,
                end=end * slot_minutes,
                buffer_end=(
                    end * slot_minutes + context.tasks[index].buffer_min
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
            solver_status=result.status,
        )

    @staticmethod
    def provably_infeasible(context):
        """Điều kiện cần để xếp đủ mọi task: với mỗi khoảng [a, b], tổng
        thời lượng (cộng buffer) của các task nằm trọn trong khoảng đó
        không vượt quá thời gian trống.

        Trả True nghĩa là CHẮC CHẮN vô nghiệm. Trả False chỉ nghĩa là
        chưa loại được. Bước này rẻ, và giúp tránh để CP-SAT tốn thời gian
        chứng minh vô nghiệm với các bài có nhiều chunk (dễ báo UNKNOWN).
        """
        slots = free_slots(context)
        now = context.now_minute

        def free_in(left, right):
            return sum(
                max(0, min(end, right) - max(start, left))
                for start, end in slots
            )

        starts = {
            max(now, task.earliest_start) for task in context.tasks
        }
        ends = {task.deadline for task in context.tasks}

        for left in starts:
            for right in ends:
                if right <= left:
                    continue

                demand = sum(
                    task.remaining_min + task.buffer_min
                    for task in context.tasks
                    if max(now, task.earliest_start) >= left
                    and task.deadline <= right
                )

                if demand > free_in(left, right):
                    return True

        return False
    @staticmethod
    def hopeless_ids(context):
        """Task mà RIÊNG NÓ đã chắc chắn không vừa khoảng [bắt đầu, deadline]
        (thời lượng + buffer > thời gian trống). Điều kiện cần, nên an toàn
        để loại ra trước khi nhờ CP-SAT; nếu không CP-SAT có thể báo UNKNOWN
        thay vì kết luận task này không xếp được."""
        slots = free_slots(context)
        now = context.now_minute

        def free_in(left, right):
            return sum(
                max(0, min(end, right) - max(start, left))
                for start, end in slots
            )

        return {
            task.id
            for task in context.tasks
            if task.remaining_min + task.buffer_min
            > free_in(max(now, task.earliest_start), task.deadline)
        }
    def plan(
        self,
        context,
        *,
        compress_id=None,
        compression_min=1,
        compression_max=None,
        required_ids=(),
        hint=(),
    ):
        from scheduling_algorithm.core_algorithm.models import FixedTask
        from scheduling_algorithm.core_algorithm.solve import solve

        # Vô nghiệm hiển nhiên: trả lời ngay thay vì chờ CP-SAT chứng minh.
        if (
            self.require_all
            and compress_id is None
            and self.provably_infeasible(context)
        ):
            self.last_status = "INFEASIBLE"

            return PlanResult(
                status="NOT_FOUND",
                chunks=[],
                unscheduled={
                    task.id: task.remaining_min
                    for task in context.tasks
                },
                solver_status="INFEASIBLE",
            )
        # Baseline (require_all=False): task đã chắc chắn không vừa thì
        # đánh dấu chưa xếp ngay, chỉ nhờ CP-SAT xếp phần còn lại.
        if not self.require_all and compress_id is None:
            hopeless = self.hopeless_ids(context)

            if hopeless:
                skipped = {
                    task.id: task.remaining_min
                    for task in context.tasks
                    if task.id in hopeless
                }

                reduced = context.model_copy(deep=True)
                reduced.tasks = [
                    task
                    for task in reduced.tasks
                    if task.id not in hopeless
                ]

                if not reduced.tasks:
                    self.last_status = "INFEASIBLE"

                    return PlanResult(
                        status="NOT_FOUND",
                        chunks=[],
                        unscheduled=skipped,
                        solver_status="INFEASIBLE",
                    )

                result = self.plan(
                    reduced,
                    required_ids=set(required_ids) - hopeless,
                    hint=hint,
                )

                if result.status == "UNKNOWN":
                    return result

                return result.model_copy(
                    update={
                        "status": "NOT_FOUND",
                        "unscheduled": {
                            **result.unscheduled,
                            **skipped,
                        },
                    }
                )
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

        slot = self._slot_minutes(context)

        result = solve(
            self._core_tasks(context),
            fixed,
            self._config(slot),
            require_all=self.require_all,
            backward=self.backward,
            compress_id=compressed_index,
            compression_min=compression_min,
            compression_max=compression_max,
            required_ids=protected_indices,
            hint=self._hint(context, hint),
        )

        return self._plan_result(context, result, slot)
        
    def max_placeable(self, context, target_id):
        """Số phút lớn nhất của target còn xếp được khi giữ nguyên
        các task khác. Dùng để đo thiếu hụt thật."""
        target = next(
            task
            for task in context.tasks
            if task.id == target_id
        )

        if target.remaining_min <= 1:
            return 0

        result = self.plan(
            context,
            compress_id=target_id,
            compression_min=1,
        )

        if result.status != "FEASIBLE":
            return 0

        return sum(
            chunk.end - chunk.start
            for chunk in result.chunks
            if chunk.task_id == target_id
        )

    def plan_relaxed(self, context, blocks, *, step=15):
        """Một lần giải: nới ít nhất để xếp đủ mọi task.

        Trả về (PlanResult, {block_index: (cắt_trái, cắt_phải)},
        {khóa nhóm fixed bị xóa}).
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

        return (
            self._plan_result(context, result),
            result.elastic,
            result.removed,
        )