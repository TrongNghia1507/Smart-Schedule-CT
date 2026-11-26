"""Chỉ số khách quan của một lịch, tính từ context/result của bộ xếp lịch.

Các chỉ số tương ứng với những trục thường dùng trên biểu đồ Pareto trade-off
của bài toán xếp lịch: độ phủ, ưu tiên, đúng hạn, liền mạch, cân bằng tải và
mức hy sinh ràng buộc. Hàm chỉ đọc dữ liệu, không chạy lại solver.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from statistics import mean, pstdev

DAY = 1440
LATE_AFTER = 21 * 60      # làm việc sau 21:00 tính là "khuya"
EARLY_BEFORE = 7 * 60     # làm việc trước 07:00 tính là "quá sớm"
HEAVY_DAY_MIN = 8 * 60    # ngày làm trên 8 giờ tính là "nặng"
SHORT_CHUNK_MIN = 30


def _overlap(a_start, a_end, b_start, b_end) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def _union_length(intervals) -> int:
    total, cursor_end = 0, None
    for start, end in sorted(intervals):
        if cursor_end is None or start > cursor_end:
            total += end - start
            cursor_end = end
        elif end > cursor_end:
            total += end - cursor_end
            cursor_end = end
    return total


def _odd_hours(start: int, end: int) -> int:
    """Số phút của [start, end) nằm ngoài khung 07:00–21:00 theo từng ngày."""
    minutes = 0
    for day in range(start // DAY, (end - 1) // DAY + 1):
        base = day * DAY
        minutes += _overlap(start, end, base, base + EARLY_BEFORE)
        minutes += _overlap(start, end, base + LATE_AFTER, base + DAY)
    return minutes


def schedule_key(context: dict, result: dict, week_start: str) -> str:
    """Mã định danh ổn định của một lịch cụ thể (cùng lịch → cùng mã)."""
    payload = {
        "week": week_start,
        "chunks": sorted((c["task_id"], c["start"], c["end"]) for c in result.get("chunks", [])),
        "unscheduled": sorted((result.get("unscheduled") or {}).items()),
        "version": context.get("schedule_version", 0),
    }
    return hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def compute_schedule_metrics(context: dict, result: dict, applied_options: list[dict] | None = None) -> dict:
    tasks = {task["id"]: task for task in context.get("tasks", [])}
    chunks = list(result.get("chunks", []))
    unscheduled = result.get("unscheduled") or {}
    applied = list(applied_options or [])

    by_task = defaultdict(list)
    for chunk in chunks:
        by_task[chunk["task_id"]].append(chunk)

    # ---- Độ phủ -------------------------------------------------------
    placed_minutes = {tid: sum(c["end"] - c["start"] for c in by_task.get(tid, [])) for tid in tasks}
    required = {tid: task["remaining_min"] for tid, task in tasks.items()}
    fully_placed = [tid for tid in tasks if unscheduled.get(tid, 0) == 0 and by_task.get(tid)]
    required_total = sum(required.values())
    placed_total = sum(min(placed_minutes[tid], required[tid]) for tid in tasks)

    # ---- Ưu tiên ------------------------------------------------------
    importance_total = sum(task["importance"] for task in tasks.values())
    importance_done = sum(tasks[tid]["importance"] for tid in fully_placed)
    mandatory = [tid for tid, task in tasks.items() if task["mandatory"]]
    mandatory_done = [tid for tid in mandatory if tid in fully_placed]
    high = [tid for tid, task in tasks.items() if task["importance"] == 3]
    high_done = [tid for tid in high if tid in fully_placed]

    # ---- Đúng hạn và dư địa ------------------------------------------
    slacks = []
    for tid in fully_placed:
        last_end = max(c["end"] for c in by_task[tid])
        slacks.append(tasks[tid]["deadline"] - last_end)
    on_time = sum(1 for s in slacks if s >= 0)

    # ---- Liền mạch ----------------------------------------------------
    lengths = [c["end"] - c["start"] for c in chunks]
    pieces = [len(v) for v in by_task.values()]

    # ---- Cân bằng tải và nghỉ ngơi -----------------------------------
    active_days = sorted({w["start"] // DAY for w in context.get("active_windows", [])})
    day_load = defaultdict(int)
    for chunk in chunks:
        day_load[chunk["start"] // DAY] += chunk["end"] - chunk["start"]
    loads = [day_load.get(day, 0) for day in active_days] or [0]
    ordered = sorted(chunks, key=lambda c: c["start"])
    gaps = [b["start"] - a["end"] for a, b in zip(ordered, ordered[1:])
            if b["start"] // DAY == a["end"] // DAY and b["start"] >= a["end"]]
    odd_minutes = sum(_odd_hours(c["start"], c["end"]) for c in chunks)

    # ---- Mức lấp đầy khung giờ rảnh ----------------------------------
    windows = [(w["start"], w["end"]) for w in context.get("active_windows", [])]
    fixed = [(f["interval"]["start"], f["interval"]["end"]) for f in context.get("fixed_tasks", [])]
    window_total = _union_length(windows)
    busy_in_windows = _union_length(
        [(max(a, s), min(b, e)) for a, b in windows for s, e in fixed if _overlap(a, b, s, e)]
    )
    free_total = max(1, window_total - busy_in_windows)

    # ---- Ràng buộc đã bị điều chỉnh ----------------------------------
    dropped = reduced = removed_events = removed_minutes = widened_minutes = 0
    reduced_minutes = 0
    for action in applied:
        payload = action.get("action_payload") or {}
        operation = payload.get("operation")
        if operation == "EXCLUDE_FROM_WEEK" or action.get("option_id") == 1:
            dropped += 1
        elif operation == "COMPRESS_TASK" or action.get("option_id") == 2:
            reduced += 1
            new = action.get("duration_min") or payload.get("new_duration")
            if payload.get("old_duration") and new:
                reduced_minutes += max(0, payload["old_duration"] - new)
        for change in payload.get("changes", []):
            if change.get("operation") == "REMOVE_FIXED":
                removed_events += 1
                removed_minutes += change.get("removed_minutes", 0)
            elif change.get("operation") == "EXPAND_ACTIVE_WINDOW":
                widened_minutes += change.get("earlier_minutes", 0) + change.get("later_minutes", 0)

    def ratio(a, b):
        return round(a / b, 4) if b else None

    return {
        "tasks_total": len(tasks),
        "tasks_fully_placed": len(fully_placed),
        "tasks_unplaced": len(tasks) - len(fully_placed),
        "coverage_task_ratio": ratio(len(fully_placed), len(tasks)),
        "required_minutes": required_total,
        "placed_minutes": placed_total,
        "coverage_minutes_ratio": ratio(placed_total, required_total),
        "priority_weighted_ratio": ratio(importance_done, importance_total),
        "mandatory_total": len(mandatory),
        "mandatory_placed": len(mandatory_done),
        "high_importance_total": len(high),
        "high_importance_placed": len(high_done),
        "on_time_tasks": on_time,
        "on_time_ratio": ratio(on_time, len(slacks)),
        "min_slack_min": min(slacks) if slacks else None,
        "avg_slack_min": round(mean(slacks)) if slacks else None,
        "chunks_total": len(chunks),
        "avg_chunk_min": round(mean(lengths)) if lengths else None,
        "short_chunks": sum(1 for x in lengths if x < SHORT_CHUNK_MIN),
        "tasks_split": sum(1 for x in pieces if x > 1),
        "max_pieces_per_task": max(pieces) if pieces else 0,
        "max_day_minutes": max(loads),
        "avg_day_minutes": round(mean(loads)),
        "day_load_cv": round(pstdev(loads) / mean(loads), 3) if mean(loads) else 0,
        "heavy_days": sum(1 for x in loads if x > HEAVY_DAY_MIN),
        "avg_gap_min": round(mean(gaps)) if gaps else None,
        "odd_hour_minutes": odd_minutes,
        "utilization_ratio": ratio(placed_total, free_total),
        "options_applied": len(applied),
        "dropped_tasks": dropped,
        "reduced_tasks": reduced,
        "reduced_minutes": reduced_minutes,
        "removed_fixed_events": removed_events,
        "removed_fixed_minutes": removed_minutes,
        "widened_minutes": widened_minutes,
        "proven_optimal": result.get("solver_status") == "OPTIMAL",
        "complete": not unscheduled and len(fully_placed) == len(tasks),
    }


def _hm(minutes) -> str:
    if minutes is None:
        return "—"
    sign = "-" if minutes < 0 else ""
    minutes = abs(int(minutes))
    h, m = divmod(minutes, 60)
    return f"{sign}{h} giờ {m:02d} phút" if h else f"{sign}{m} phút"


def _pct(value) -> str:
    return "—" if value is None else f"{value * 100:.0f}%"


def criterion_facts(m: dict) -> dict[str, list[str]]:
    """Dòng 'hệ thống đo được' hiển thị cạnh từng tiêu chí để người dùng chấm có cơ sở."""
    changes = []
    if m["dropped_tasks"]:
        changes.append(f"bỏ {m['dropped_tasks']} việc")
    if m["reduced_tasks"]:
        changes.append(f"giảm thời lượng {m['reduced_tasks']} việc (−{_hm(m['reduced_minutes'])})")
    if m["removed_fixed_events"]:
        changes.append(f"xoá {m['removed_fixed_events']} sự kiện cố định")
    if m["widened_minutes"]:
        changes.append(f"nới giờ thức/ngủ {_hm(m['widened_minutes'])}")
    return {
        "coverage": [
            f"Xếp đủ {m['tasks_fully_placed']}/{m['tasks_total']} việc ({_pct(m['coverage_task_ratio'])})",
            f"Thời lượng đã xếp {_hm(m['placed_minutes'])}/{_hm(m['required_minutes'])} ({_pct(m['coverage_minutes_ratio'])})",
        ],
        "priority": [
            f"Điểm ưu tiên đạt được {_pct(m['priority_weighted_ratio'])}",
            f"Việc bắt buộc {m['mandatory_placed']}/{m['mandatory_total']} · mức quan trọng ③ {m['high_importance_placed']}/{m['high_importance_total']}",
        ],
        "timeliness": [
            f"Đúng hạn {m['on_time_tasks']}/{m['tasks_fully_placed']} việc đã xếp",
            f"Dư địa trước hạn: ít nhất {_hm(m['min_slack_min'])} · trung bình {_hm(m['avg_slack_min'])}",
        ],
        "continuity": [
            f"{m['chunks_total']} phiên làm việc, trung bình {_hm(m['avg_chunk_min'])}/phiên",
            f"{m['tasks_split']} việc bị chia nhiều phiên · {m['short_chunks']} phiên dưới {SHORT_CHUNK_MIN} phút",
        ],
        "balance": [
            f"Ngày nặng nhất {_hm(m['max_day_minutes'])} · trung bình {_hm(m['avg_day_minutes'])}/ngày",
            f"Nghỉ trung bình giữa các phiên {_hm(m['avg_gap_min'])} · làm ngoài 07:00–21:00: {_hm(m['odd_hour_minutes'])}",
        ],
        "constraints": [
            ("Đã điều chỉnh: " + "; ".join(changes)) if changes else "Không phải điều chỉnh ràng buộc nào",
            f"Số phương án xử lý xung đột đã áp dụng: {m['options_applied']}",
        ],
        "realism": [
            f"Lấp đầy {_pct(m['utilization_ratio'])} thời gian rảnh trong khung thức",
            "Lịch được chứng minh tối ưu" if m["proven_optimal"] else "Lịch tốt nhất tìm được trong thời gian giới hạn",
        ],
    }
