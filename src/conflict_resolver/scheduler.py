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