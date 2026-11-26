"""Chuyển dòng MySQL <-> đối tượng lõi (ScheduleInput, InputSnapshot, ConflictContext)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime

from conflict_resolver.models import ConflictContext, Policy
from conflict_resolver.planning import context_from_snapshot
from schedule_input.application.mapper import TaskFactory
from schedule_input.application.parsers import DateTimeParser
from schedule_input.application.preview import SnapshotBuilder
from schedule_input.domain.models import PlanningWindow, ScheduleInput, SleepWindow, TimeRange
from schedule_input.domain.validation import ValidationService, free_minutes
from schedule_preparation.ui_adapter import UiMeta, snapshot_to_raw

from .errors import CannotPlanError, InputInvalidError, issue_dict

SETTING_KEYS = ("sleep_start", "sleep_end", "max_earlier_min", "max_later_min")


# ---------------------------------------------------------------- đọc từ DB
def default_settings(week_start: date) -> dict:
    return {"week_start": week_start, "sleep_start": "23:00", "sleep_end": "06:30",
            "max_earlier_min": 0, "max_later_min": 0, "_exists": False}


def fetch_week_rows(cur, user_id: int, week_start: date):
    """Trả (settings, fixed_rows, deadline_rows) của đúng user và tuần."""
    cur.execute("SELECT * FROM user_week_settings WHERE user_id=%s AND week_start=%s",
                (user_id, week_start))
    row = cur.fetchone()
    settings = {**row, "_exists": True} if row else default_settings(week_start)
    cur.execute("SELECT * FROM fixed_tasks WHERE user_id=%s AND week_start=%s ORDER BY id",
                (user_id, week_start))
    fixed_rows = list(cur.fetchall())
    cur.execute("SELECT * FROM deadline_tasks WHERE user_id=%s AND week_start=%s ORDER BY id",
                (user_id, week_start))
    deadline_rows = list(cur.fetchall())
    return settings, fixed_rows, deadline_rows


def _iso_minutes(value) -> str:
    if isinstance(value, datetime):
        return value.isoformat(timespec="minutes")
    return str(value).replace(" ", "T")[:16]


def fixed_row_to_core_dict(row: dict, with_color: bool = False) -> dict:
    out = {
        "id": row["task_code"], "name": row["name"],
        "repeat_days": [d for d in (row["repeat_days"] or "").split(",") if d],
        "one_off_date": row["one_off_date"].isoformat() if row["one_off_date"] else None,
        "start": row["start_time"], "end": row["end_time"],
        "prep_min": int(row["prep_min"]), "after_min": int(row["after_min"]),
        "removable_when_busy": bool(row["removable_when_busy"]),
    }
    if with_color:
        out["display_color"] = row.get("display_color")
    return out


def deadline_row_to_core_dict(row: dict) -> dict:
    return {
        "id": row["task_code"], "name": row["name"],
        "mandatory": bool(row["mandatory"]), "importance": int(row["importance"]),
        "deadline": _iso_minutes(row["deadline"]),
        "remaining_min": int(row["remaining_min"]), "focus": row["focus"],
        "buffer_min": int(row["buffer_min"]),
        "earliest_start": _iso_minutes(row["earliest_start"]) if row["earliest_start"] else None,
        "chunk_min": int(row["chunk_min"]), "chunk_max": int(row["chunk_max"]),
    }


def core_inputs(fixed_rows, deadline_rows, with_color: bool = False):
    return ([fixed_row_to_core_dict(r, with_color) for r in fixed_rows],
            [deadline_row_to_core_dict(r) for r in deadline_rows])


def settings_dict(settings: dict) -> dict:
    return {k: settings[k] for k in SETTING_KEYS}


def input_hash(settings: dict, fixed_rows, deadline_rows) -> str:
    fixed, deadline = core_inputs(fixed_rows, deadline_rows)
    payload = {"s": settings_dict(settings),
               "f": sorted(fixed, key=lambda t: t["id"]),
               "d": sorted(deadline, key=lambda t: t["id"])}
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------- dict lõi -> ScheduleInput
def issues_to_dicts(issues) -> list[dict]:
    return [issue_dict(i.code, i.severity.value, i.field, i.task_id, i.message) for i in issues]


def build_schedule_input_from_core(week_start: date, settings: dict, fixed_dicts: list,
                                   deadline_dicts: list, now: datetime):
    """Trả (ScheduleInput, danh_sách_issue_parse). Sai giờ ngủ -> InputInvalidError."""
    try:
        start = DateTimeParser.time(settings["sleep_start"])
        end = DateTimeParser.time(settings["sleep_end"], True)
        TimeRange(start, end)
    except ValueError as exc:
        raise InputInvalidError([issue_dict("S01", "Error", "sleep", "", str(exc))]) from exc
    data = ScheduleInput(PlanningWindow(week_start, now, SleepWindow(start, end)))
    issues = []
    for fixed, rows in ((True, fixed_dicts), (False, deadline_dicts)):
        for raw in rows:
            task, report = TaskFactory.from_dict(raw, fixed)
            if task is None:
                issues.extend(report.issues)
            elif task.id in data._tasks:
                issues.append(issue_dict("V01", "Error", "id", task.id, "ID trùng."))
            else:
                data.add(task)
    return data, issues


def build_schedule_input(week_start: date, settings: dict, fixed_rows, deadline_rows,
                         now: datetime):
    fixed, deadline = core_inputs(fixed_rows, deadline_rows)
    data, issues = build_schedule_input_from_core(week_start, settings, fixed, deadline, now)
    return data, issues


def _parse_issue_dicts(issues) -> list[dict]:
    return [i if isinstance(i, dict) else issues_to_dicts([i])[0] for i in issues]


def validate_rows(week_start: date, settings: dict, fixed_rows, deadline_rows,
                  now: datetime) -> dict:
    data, parse_issues = build_schedule_input(week_start, settings, fixed_rows, deadline_rows, now)
    report = ValidationService().validate_all(data)
    issues = _parse_issue_dicts(parse_issues) + issues_to_dicts(report.issues)
    return {"issues": issues, "has_errors": any(i["severity"] == "Error" for i in issues),
            "free_minutes": free_minutes(data)}


# ----------------------------------------------------- ScheduleInput -> lõi
@dataclass
class BuiltContext:
    context: ConflictContext
    snapshot: dict
    meta: UiMeta
    warnings: list


def build_context(week_start: date, settings: dict, fixed_rows, deadline_rows,
                  now: datetime) -> BuiltContext:
    data, parse_issues = build_schedule_input(week_start, settings, fixed_rows, deadline_rows, now)
    report = ValidationService().validate_all(data)
    issues = _parse_issue_dicts(parse_issues) + issues_to_dicts(report.issues)
    if any(i["severity"] == "Error" for i in issues):
        raise InputInvalidError(issues)
    snapshot = SnapshotBuilder().build(data).to_dict()
    _, meta = snapshot_to_raw(snapshot)
    policy = Policy(max_earlier_minutes=int(settings["max_earlier_min"]),
                    max_later_minutes=int(settings["max_later_min"]))
    try:
        context = context_from_snapshot(snapshot, policy)
    except ValueError as exc:
        raise CannotPlanError(str(exc)) from exc
    return BuiltContext(context, snapshot, meta,
                        [i for i in issues if i["severity"] != "Error"])
