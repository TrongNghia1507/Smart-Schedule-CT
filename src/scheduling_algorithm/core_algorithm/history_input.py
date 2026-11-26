"""Rebuild editable input from a saved schedule without changing history."""
from copy import deepcopy
from datetime import date, datetime, timedelta

from schedule_input.application.mapper import TaskFactory, hh
from schedule_input.domain.models import PlanningWindow, ScheduleInput, SleepWindow


def input_from_history(record):
    """Return (input, notes), retaining selected removals and duration changes."""
    week = date.fromisoformat(record["week_start"])
    if week.weekday() != 0:
        raise ValueError("Tuần của lịch phải bắt đầu vào Thứ Hai.")
    origin = datetime.combine(week, datetime.min.time())
    context = record["context"]
    snapshot = deepcopy(record.get("input_snapshot") or {})
    notes = []
    if not snapshot:
        notes.append("Lịch cũ chưa lưu input gốc: dựng lại từ lịch đã chọn; mức tập trung mặc định là high.")
    daily = [[] for _ in range(7)]
    for window in context["active_windows"]:
        start, end = window["start"], window["end"]
        if not 0 <= start < end <= 10080:
            raise ValueError("Khung giờ trong lịch sử không hợp lệ.")
        for day in range(7):
            left, right = max(start, day * 1440), min(end, (day + 1) * 1440)
            if left < right:
                daily[day].append((left - day * 1440, right - day * 1440))
    intervals = [interval for day in daily for interval in day]
    if not intervals:
        raise ValueError("Lịch sử không có khung giờ hoạt động.")
    wake, bed = min(a for a, _ in intervals), max(b for _, b in intervals)
    sleep = SleepWindow(bed % 1440, wake)
    if sleep.start == sleep.end:
        raise ValueError("Không thể nạp khung giờ không có thời gian ngủ vào trang nhập.")
    data = ScheduleInput(PlanningWindow(week, origin, sleep))

    def add(row, fixed=False):
        task, report = TaskFactory.from_dict(row, fixed)
        if task is None or report.has_errors():
            errors = "; ".join(issue.message for issue in report.issues)
            raise ValueError(f"Không nạp được “{row.get('name', '')}”: {errors}")
        data.add(task)

    originals = {row["id"]: row for row in snapshot.get("deadline_tasks", [])}
    for task in context["tasks"]:
        row = deepcopy(originals.get(task["id"], {}))
        if not row:
            row.update(
                deadline=(origin + timedelta(minutes=task["deadline"])).isoformat(timespec="minutes"),
                earliest_start=(origin + timedelta(minutes=task["earliest_start"])).isoformat(timespec="minutes"),
                focus="high", buffer_min=task.get("buffer_min", 0),
                chunk_min=task["chunk_min"], chunk_max=task["chunk_max"],
            )
        row.update(id=task["id"], name=task["name"], mandatory=task["mandatory"],
                   importance=task["importance"], remaining_min=task["remaining_min"])
        add(row)

    if snapshot:
        from schedule_preparation.ui_adapter import snapshot_to_raw

        _, meta = snapshot_to_raw(snapshot)
        prefixes = {ui_id: engine_id for engine_id, ui_id in meta.fixed_ui_ids.items()}
        groups = {item.get("group") or item["id"].split(".")[0]
                  for item in context.get("fixed_tasks", [])}
        weekdays = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        for original in snapshot.get("fixed_tasks", []):
            row = deepcopy(original)
            prefix = prefixes.get(row["id"])
            if prefix:
                if row.get("one_off_date"):
                    day = (date.fromisoformat(row["one_off_date"]) - week).days
                    if f"{prefix}@{day}" not in groups:
                        continue
                else:
                    row["repeat_days"] = [name for name in row.get("repeat_days", [])
                                          if f"{prefix}@{weekdays.index(name)}" in groups]
                    if not row["repeat_days"]:
                        continue
            add(row, True)
    else:
        # Join midnight pieces and their preparation/travel into single events.
        groups = {}
        for item in context.get("fixed_tasks", []):
            group = item.get("group") or item["id"].split(".")[0]
            groups.setdefault(group, []).append(item)
        for group, pieces in groups.items():
            main = [item for item in pieces if not item.get("ancillary", False)]
            if not main:
                raise ValueError("Lịch cũ có khối chuẩn bị không gắn với sự kiện.")
            start = min(item["interval"]["start"] for item in main)
            end = max(item["interval"]["end"] for item in main)
            auxiliary = [item["interval"] for item in pieces if item.get("ancillary", False)]
            prep = max([0] + [start - item["start"] for item in auxiliary if item["end"] <= start])
            after = max([0] + [item["end"] - end for item in auxiliary if item["start"] >= end])
            add(dict(id=group, name=main[0]["name"], repeat_days=[],
                     one_off_date=(origin + timedelta(minutes=start)).date().isoformat(),
                     start=hh(start % 1440), end=hh(end % 1440 or 1440),
                     prep_min=prep, after_min=after,
                     removable_when_busy=main[0].get("can_remove", False)), True)

    # The editor has one global sleep setting. Fixed blocks preserve any
    # per-day active-window limits without widening the chosen schedule.
    for day, allowed in enumerate(daily):
        cursor, gaps = wake, []
        for start, end in sorted(allowed):
            if cursor < start:
                gaps.append((cursor, start))
            cursor = max(cursor, end)
        if cursor < bed:
            gaps.append((cursor, bed))
        # Existing events may already reserve some of this time (including
        # travel). Avoid overlapping editor rows while retaining the same union.
        day_origin = origin + timedelta(days=day)
        occupied = sorted(
            (int((a - day_origin).total_seconds() // 60),
             int((b - day_origin).total_seconds() // 60))
            for task in data.fixed_tasks for a, b in task.occupied_occurrences(week)
        )
        for left, right in occupied:
            remaining = []
            for start, end in gaps:
                if right <= start or left >= end:
                    remaining.append((start, end))
                else:
                    if start < left:
                        remaining.append((start, left))
                    if right < end:
                        remaining.append((right, end))
            gaps = remaining
        for index, (start, end) in enumerate(gaps):
            task_id = f"history_window_{day}_{index}"
            while task_id in data._tasks:
                task_id += "_"
            add(dict(id=task_id, name="Ngoài khung giờ đã chọn", repeat_days=[],
                     one_off_date=(week + timedelta(days=day)).isoformat(),
                     start=hh(start), end=hh(end), removable_when_busy=False), True)
    if any(len(day) != 1 or day[0] != (wake, bed) for day in daily):
        notes.append("Khung giờ khác nhau theo ngày được giữ bằng các việc cố định “Ngoài khung giờ đã chọn”.")
    return data, notes
