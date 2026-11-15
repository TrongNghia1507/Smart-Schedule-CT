"""Kiểm tra cân đối thời gian: nhu cầu trước mỗi hạn chót so với thời gian trống từ đầu đến mốc đó."""
from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True)
class Checkpoint:
    deadline: int          # mốc kiểm tra (phút trong tuần)
    window_start: int      # đầu khoảng so sánh (bây giờ, hoặc earliest_start của nhóm)
    demand: int            # tổng (remaining + buffer) của các task nằm trọn trong [window_start, deadline]
    free: int              # phút trống trong [window_start, deadline]
    task_ids: tuple
    target_id: str         # task "đang xếp" tại mốc này

    @property
    def deficit(self):
        return self.demand - self.free

    @property
    def conflict(self):
        return self.demand > self.free


def demand_of(task):
    # Thời lượng + một khoảng nghỉ đệm sau cả việc (đúng mô tả ở giao diện nhập).
    return task.remaining_min + task.buffer_min


def free_intervals(model):
    """Khoảng trống = khung hoạt động (đã trừ giờ ngủ) từ bây giờ, trừ các việc cố định."""
    slots = [
        (max(w.start, model.now_min), w.end)
        for w in model.windows if max(w.start, model.now_min) < w.end
    ]
    for occ in model.occurrences:
        updated = []
        for start, end in slots:
            if occ.end <= start or occ.start >= end:
                updated.append((start, end))
                continue
            if start < occ.start:
                updated.append((start, occ.start))
            if occ.end < end:
                updated.append((occ.end, end))
        slots = updated
    return sorted(slots)


def capacity_checkpoints(model):
    """Một Checkpoint cho mỗi hạn chót khác nhau, chọn khoảng bất lợi nhất.

    Với a = bây giờ đây chính là phép so "việc có deadline trước mốc" với
    "thời gian trống từ đầu đến mốc". Các a > bây giờ (earliest_start) bổ sung
    điều kiện cho nhóm task chỉ làm được từ giữa tuần.
    """
    if not model.checkable:
        return []

    slots = free_intervals(model)

    def free(a, b):
        return sum(max(0, min(end, b) - max(start, a)) for start, end in slots)

    starts = sorted({model.now_min, *model.effective_start.values()})
    checkpoints = []

    for deadline in sorted({t.deadline for t in model.tasks}):
        worst = None
        for a in starts:
            if a >= deadline:
                continue
            group = [
                t for t in model.tasks
                if t.deadline <= deadline and model.effective_start[t.id] >= a
            ]
            tied = [t.id for t in group if t.deadline == deadline]
            if not tied:
                continue  # đã bị mốc nhỏ hơn bao trùm

            candidate = Checkpoint(
                deadline=deadline,
                window_start=a,
                demand=sum(demand_of(t) for t in group),
                free=free(a, deadline),
                task_ids=tuple(t.id for t in group),
                target_id=model.pick_target(tied).id,
            )
            if worst is None or candidate.deficit > worst.deficit:
                worst = candidate

        if worst:
            checkpoints.append(worst)

    return checkpoints
