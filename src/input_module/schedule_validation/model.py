"""Adapter: ScheduleInput (datetime) -> các đối tượng của conflict_resolver (phút trong tuần)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from conflict_resolver.models import (
    WEEK,
    ConflictContext,
    FixedTask as CtxFixed,
    Interval,
    Policy,
    Task as CtxTask,
)
from schedule_input.domain.models import DeadlineTask
from schedule_input.domain.validation import sleep_bands

from .policy import ResolutionPolicy

DAY_NAMES = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ nhật"]


def describe_minute(minute):
    if minute >= WEEK:
        return "hết tuần (24:00 Chủ nhật)"
    day, rest = divmod(int(minute), 1440)
    return f"{DAY_NAMES[day]} {rest // 60:02}:{rest % 60:02}"


@dataclass(frozen=True)
class Occurrence:
    ctx_id: str
    task_id: str
    name: str
    start: int          # đã cắt vào [0, WEEK), gồm prep + after
    end: int
    shortenable: bool
    min_duration: int


@dataclass(frozen=True)
class SkippedTask:
    task_id: str
    name: str
    code: str           # AFTER_WEEK | EMPTY_WINDOW
    reason: str


@dataclass
class WeekModel:
    week_start: datetime
    now_min: int
    windows: list
    occurrences: list
    tasks: list                                   # CtxTask
    origins: dict                                 # task_id -> DeadlineTask
    effective_start: dict                         # task_id -> max(earliest_start, now)
    skipped: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    policy: ResolutionPolicy = field(default_factory=ResolutionPolicy)
    reason: str | None = None                     # khác None = không kiểm tra được

    @property
    def checkable(self):
        return self.reason is None and bool(self.tasks)

    def to_datetime(self, minute):
        if minute >= WEEK:
            # Quy ước của input module cho "hết tuần": 23:59 Chủ nhật.
            return datetime.combine(
                self.week_start.date() + timedelta(days=6), time(23, 59)
            )
        return self.week_start + timedelta(minutes=int(minute))

    def occurrence(self, ctx_id):
        return next((o for o in self.occurrences if o.ctx_id == ctx_id), None)

    # -- dựng ConflictContext cho "tiền tố" các task có deadline <= cutoff ----
    def _fixed_for(self, cutoff):
        def touches_window(o):
            return any(o.start < w.end and o.end > w.start for w in self.windows)

        relevant = [
            o for o in self.occurrences
            if o.end > self.now_min
            and (cutoff is None or o.start < cutoff)
            and touches_window(o)
        ]

        result = [
            CtxFixed(
                id=o.ctx_id,
                name=o.name,
                interval=Interval(start=o.start, end=o.end),
                importance=self.policy.shortenable_fixed_importance,
                can_shorten=True,
                min_duration=o.min_duration,
            )
            for o in relevant if o.shortenable
        ]

        # Gộp các khối cứng chồng/chạm nhau: không đổi ý nghĩa, giữ dưới giới hạn 200.
        rigid = sorted((o.start, o.end) for o in relevant if not o.shortenable)
        merged = []
        for start, end in rigid:
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])

        for index, (start, end) in enumerate(merged):
            result.append(
                CtxFixed(
                    id=f"rigid#{index}",
                    name="Việc cố định",
                    interval=Interval(start=start, end=end),
                    importance=self.policy.rigid_fixed_importance,
                )
            )
        return result

    def context_for(self, cutoff, target_id, conflict_id, version=0):
        tasks = [t for t in self.tasks if cutoff is None or t.deadline <= cutoff]
        return ConflictContext(
            conflict_id=conflict_id,
            schedule_version=version,
            now_minute=self.now_min,
            target_task_id=target_id,
            tasks=tasks,
            fixed_tasks=self._fixed_for(cutoff),
            active_windows=list(self.windows),
            policy=Policy(
                max_earlier_minutes=min(60, max(0, self.policy.max_earlier_minutes)),
                max_later_minutes=min(60, max(0, self.policy.max_later_minutes)),
                compression_step_minutes=min(60, max(1, self.policy.compression_step_minutes)),
            ),
        )

    def pick_target(self, task_ids):
        """Task "đang xếp" tại một mốc: quan trọng nhất, rồi dài nhất."""
        candidates = [t for t in self.tasks if t.id in set(task_ids)]
        return min(candidates, key=lambda t: (-t.importance, -t.remaining_min, t.id))


def _minute(week_start, value):
    return int((value - week_start).total_seconds() // 60)


def _awake_windows(data, week_start):
    bands = []
    for a, b in sleep_bands(data):
        start, end = max(0, _minute(week_start, a)), min(WEEK, _minute(week_start, b))
        if start < end:
            bands.append((start, end))

    merged = []
    for start, end in sorted(bands):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    windows, cursor = [], 0
    for start, end in merged:
        if start > cursor:
            windows.append(Interval(start=cursor, end=start))
        cursor = max(cursor, end)
    if cursor < WEEK:
        windows.append(Interval(start=cursor, end=WEEK))
    return windows


def _convert_task(t: DeadlineTask, now_min, week_start, policy, model_notes):
    """Trả về (CtxTask | None, effective_start | None, SkippedTask | None)."""
    deadline = _minute(week_start, t.deadline)
    earliest = _minute(week_start, t.earliest_start) if t.earliest_start else 0
    earliest = max(0, earliest)

    if deadline > WEEK:
        if policy.out_of_week_deadline == "skip":
            return None, None, SkippedTask(
                t.id, t.name, "AFTER_WEEK",
                "Hạn chót sau tuần lập lịch nên không tính vào tuần này.",
            )
        deadline = WEEK
        model_notes.append(
            f"“{t.name}”: hạn chót nằm sau tuần, được tính như phải xong trong tuần."
        )

    if earliest >= WEEK:
        return None, None, SkippedTask(
            t.id, t.name, "AFTER_WEEK",
            "Bắt đầu sớm nhất sau tuần lập lịch nên không tính vào tuần này.",
        )

    effective = max(earliest, now_min)
    if deadline <= effective or earliest >= deadline:
        return None, None, SkippedTask(
            t.id, t.name, "EMPTY_WINDOW",
            "Không còn khoảng thời gian hợp lệ nào từ bây giờ đến hạn chót trong tuần.",
        )

    remaining = min(max(1, t.remaining_min), WEEK)
    if t.remaining_min > WEEK:
        model_notes.append(f"“{t.name}”: thời lượng vượt một tuần, đã giới hạn ở 7 ngày.")

    chunk_min = min(t.chunk.min_min, WEEK)
    chunk_max = min(t.chunk.max_min, WEEK)

    rule = policy.rule_for(t.id, t.kind.value)

    if rule.allow_compress:
        floor = max(math.ceil(remaining * rule.min_keep_ratio), min(chunk_min, remaining), 1)
        min_remaining = min(floor, remaining)
    else:
        min_remaining = remaining

    max_postpone = (WEEK - deadline) if rule.allow_postpone else 0

    task = CtxTask(
        id=t.id,
        name=t.name,
        kind=t.kind.value,
        importance=t.importance,
        remaining_min=remaining,
        earliest_start=earliest,
        deadline=deadline,
        chunk_min=chunk_min,
        chunk_max=chunk_max,
        buffer_min=t.buffer.minutes,
        allow_compress=rule.allow_compress,
        min_remaining_min=min_remaining,
        allow_exclude=rule.allow_exclude,
        max_postpone_minutes=max_postpone,
    )
    return task, effective, None


def build_week_model(data, policy=None) -> WeekModel:
    policy = policy or ResolutionPolicy()
    week_start = datetime.combine(data.window.week_start, time.min)

    raw_now = _minute(week_start, data.window.now)
    base = dict(
        week_start=week_start, windows=[], occurrences=[], tasks=[], origins={},
        effective_start={}, policy=policy,
    )

    if raw_now >= WEEK:
        return WeekModel(now_min=0, reason="Tuần lập lịch đã kết thúc.", **base)

    now_min = max(0, raw_now)
    windows = _awake_windows(data, week_start)
    if not windows:
        return WeekModel(now_min=now_min, reason="Giờ ngủ phủ kín cả tuần, không có thời gian hoạt động.", **base)

    occurrences = []
    for t in data.fixed_tasks:
        for a, b in t.occurrences(data.window.week_start):
            start = max(0, _minute(week_start, a - timedelta(minutes=t.prep_min)))
            end = min(WEEK, _minute(week_start, b + timedelta(minutes=t.after_min)))
            if start >= end:
                continue

            core_len = min(WEEK, _minute(week_start, b)) - max(0, _minute(week_start, a))
            shortenable = (
                t.is_flexible
                and t.flexibility.min_min < t.duration_min
                and core_len > t.flexibility.min_min
            )
            # Chỉ phần lõi được co; prep/after giữ nguyên nên cộng vào mức tối thiểu.
            min_duration = (end - start) - core_len + t.flexibility.min_min if shortenable else 1

            occurrences.append(Occurrence(
                ctx_id=f"{t.id}@{a:%Y%m%d%H%M}", task_id=t.id, name=t.name,
                start=start, end=end, shortenable=shortenable, min_duration=min_duration,
            ))

    notes, skipped, tasks, origins, effective = [], [], [], {}, {}
    for t in data.deadline_tasks:
        task, eff, skip = _convert_task(t, now_min, week_start, policy, notes)
        if skip:
            skipped.append(skip)
            continue
        tasks.append(task)
        origins[t.id] = t
        effective[t.id] = eff

    return WeekModel(
        week_start=week_start, now_min=now_min, windows=windows,
        occurrences=occurrences, tasks=tasks, origins=origins,
        effective_start=effective, skipped=skipped, notes=notes, policy=policy,
    )
