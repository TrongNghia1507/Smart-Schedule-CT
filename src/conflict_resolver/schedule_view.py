"""Dựng bảng lịch hoàn chỉnh cho từng option.

Bảng = các sự kiện cố định còn lại trong `candidate` (option 3 có thể đã
xóa một số) + mọi chunk của task được giữ, sắp theo thời gian.
Hàm thuần: không sửa input.
"""

from .models import ScheduleEntry


def build_full_schedule(candidate, chunks):
    names = {task.id: task.name for task in candidate.tasks}

    entries = [
        ScheduleEntry(
            kind="TASK",
            ref_id=chunk.task_id,
            name=names.get(chunk.task_id, chunk.task_id),
            start=chunk.start,
            end=chunk.end,
            buffer_end=chunk.buffer_end,
        )
        for chunk in chunks
    ]

    entries += [
        ScheduleEntry(
            kind="FIXED",
            ref_id=fixed.id,
            name=fixed.name,
            start=fixed.interval.start,
            end=fixed.interval.end,
            ancillary=fixed.ancillary,
        )
        for fixed in candidate.fixed_tasks
    ]

    entries.sort(key=lambda entry: (entry.start, entry.end, entry.ref_id))

    return entries