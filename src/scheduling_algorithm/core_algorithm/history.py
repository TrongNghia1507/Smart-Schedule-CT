"""Persist schedules explicitly selected by the user, in minute units."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from uuid import uuid4


DEFAULT_HISTORY_PATH = Path(__file__).resolve().parent.parent / "history" / "schedule_history.json"
_HISTORY_LOCK = Lock()
_LOCAL_TIMEZONE = timezone(timedelta(hours=7), name="Asia/Saigon")
OPTION_NAMES = {
    1: "Bỏ task khỏi tuần",
    2: "Giảm thời lượng task",
    3: "Nới ràng buộc",
}


def _as_dict(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value)


def _read_history_document(path: Path) -> dict:
    try:
        history = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {"schema_version": 1, "schedules": []}
    except json.JSONDecodeError as exc:
        raise ValueError("File history không phải JSON hợp lệ; chưa ghi đè dữ liệu.") from exc
    if (not isinstance(history, dict)
            or history.get("schema_version") != 1
            or not isinstance(history.get("schedules"), list)
            or any(not isinstance(item, dict) for item in history["schedules"])):
        raise ValueError("Cấu trúc file history không hợp lệ; chưa ghi đè dữ liệu.")
    return history


def load_schedule_history(path: str | Path = DEFAULT_HISTORY_PATH) -> list[dict]:
    """Read saved snapshots, newest first, without writing or running CP-SAT."""
    with _HISTORY_LOCK:
        return list(reversed(_read_history_document(Path(path))["schedules"]))


def _write_history_document(destination: Path, history: dict) -> None:
    """Replace the file only after the complete new document is written."""
    serialized = json.dumps(history, ensure_ascii=False, indent=2, allow_nan=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                dir=destination.parent, prefix=destination.name + ".",
                                suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(serialized + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def delete_schedule_history(record_id: str, path: str | Path = DEFAULT_HISTORY_PATH) -> None:
    """Delete only the selected record from this history file."""
    if not isinstance(record_id, str) or not record_id:
        raise ValueError("ID lịch sử không hợp lệ.")
    destination = Path(path)
    with _HISTORY_LOCK:
        history = _read_history_document(destination)
        remaining = [record for record in history["schedules"] if record.get("id") != record_id]
        if len(remaining) == len(history["schedules"]):
            raise ValueError("Lịch đã bị xóa hoặc không còn tồn tại. Hãy tải lại lịch sử.")
        history["schedules"] = remaining
        _write_history_document(destination, history)


def _describe_option(action: dict, week_start: date) -> str:
    option_id = action.get("option_id")
    name = action.get("target_task_name") or action.get("target_task_id", "task đang xử lý")
    payload = action.get("action_payload") or {}
    label = f"Option {option_id}: {OPTION_NAMES.get(option_id, 'Điều chỉnh lịch')}"
    if option_id == 1:
        return f"{label} — bỏ “{name}” khỏi kế hoạch tuần."
    if option_id == 2:
        old = payload.get("old_duration")
        new = action.get("duration_min")
        if new is None:
            new = payload.get("new_duration")
        if old is not None and new is not None:
            return f"{label} — giảm “{name}” từ {old} xuống {new} phút."
        return f"{label} — điều chỉnh thời lượng “{name}”."
    if option_id == 3:
        details = []
        for change in payload.get("changes", []):
            if change.get("operation") == "REMOVE_FIXED":
                details.append(f"xóa fixed task “{change.get('name', 'không rõ tên')}”")
            elif change.get("operation") == "EXPAND_ACTIVE_WINDOW":
                start = change.get("new_start")
                end = change.get("new_end")
                if start is not None and end is not None:
                    left = datetime.combine(week_start, datetime.min.time()) + timedelta(minutes=start)
                    right = datetime.combine(week_start, datetime.min.time()) + timedelta(minutes=end)
                    details.append(f"nới khung giờ {left:%d/%m/%Y %H:%M} – {right:%d/%m/%Y %H:%M}")
        suffix = "; ".join(details) or "điều chỉnh các ràng buộc thời gian"
        return f"{label} — {suffix}."
    return label + "."


def _schedule_metadata(context: dict, result: dict, selection: dict, start: date) -> dict:
    end = start + timedelta(days=6)
    actions = list(selection.get("applied_options") or [])
    if not actions and selection.get("source") == "conflict_option":
        actions = [{key: value for key, value in selection.items() if key != "applied_options"}]
    for action in actions:
        action["option_name"] = OPTION_NAMES.get(action.get("option_id"), "Điều chỉnh lịch")
        action["description"] = _describe_option(action, start)

    schedule_version = context.get("schedule_version", 0)
    used_conflict = bool(actions) or schedule_version > 0
    if actions:
        method = "conflict_options"
        origin = "Đã áp dụng: " + " ".join(action["description"] for action in actions)
        if schedule_version > len(actions):
            origin += f" Còn {schedule_version - len(actions)} lần điều chỉnh trước chưa có chi tiết."
    elif used_conflict:
        method = "conflict_options_unknown"
        origin = (f"Lịch đã qua {schedule_version} lần áp dụng phương án conflict; "
                  "bản ghi chưa có chi tiết các lựa chọn đó.")
    else:
        method = "cp_sat"
        origin = "Lịch do CP-SAT xếp; chưa áp dụng phương án conflict."

    scheduled = len({chunk["task_id"] for chunk in result.get("chunks", [])})
    unplaced = len(result.get("unscheduled") or {})
    period = f"{start:%d/%m/%Y} – {end:%d/%m/%Y}"
    return {
        "week_end": end.isoformat(),
        "date_range": period,
        "schedule_version": schedule_version,
        "creation_method": method,
        "used_conflict_options": used_conflict,
        "applied_options": actions,
        "description": (f"Lịch từ {period}. {origin} "
                        f"Đã xếp {scheduled} task; còn {unplaced} task chưa xếp."),
    }


def save_selected_schedule(
    *,
    context,
    result,
    week_start: str,
    selection: dict | None = None,
    path: str | Path = DEFAULT_HISTORY_PATH,
    input_snapshot: dict | None = None,
) -> dict:
    """Append an accepted schedule; return its saved record.

    context/result accept dictionaries or the integration's Pydantic models.
    NOT_FOUND is allowed when a selected conflict option leaves other tasks
    unscheduled. Such records have complete=false. UNKNOWN is never saved.
    Calling this function does not run the solver or alter the chosen data.
    """
    start_date = date.fromisoformat(week_start)
    week_start = start_date.isoformat()
    context_data, result_data = _as_dict(context), _as_dict(result)
    if (result_data.get("status") not in ("FEASIBLE", "NOT_FOUND")
            or result_data.get("solver_status") in ("UNKNOWN", "INFEASIBLE", "MODEL_INVALID")):
        raise ValueError("Chỉ lưu lịch có kết quả đã được kiểm chứng.")

    now = datetime.now(timezone.utc)
    record = {
        "id": str(uuid4()),
        "saved_at": now.isoformat(),
        "saved_at_local": now.astimezone(_LOCAL_TIMEZONE).isoformat(),
        "saved_at_display": now.astimezone(_LOCAL_TIMEZONE).strftime("%d/%m/%Y %H:%M:%S"),
        "timezone": "Asia/Saigon",
        "week_start": week_start,
        "time_unit": "minutes",
        "time_origin": "week_start_00:00",
        "complete": result_data["status"] == "FEASIBLE" and not result_data.get("unscheduled"),
        "selection": selection or {},
        "context": context_data,
        "result": result_data,
    }
    if input_snapshot is not None:
        record["input_snapshot"] = _as_dict(input_snapshot)
    # Freeze caller-owned dictionaries and reject non-JSON values before I/O.
    record = json.loads(json.dumps(record, ensure_ascii=False, allow_nan=False))
    record.update(_schedule_metadata(record["context"], record["result"], record["selection"], start_date))
    destination = Path(path)

    with _HISTORY_LOCK:
        history = _read_history_document(destination)

        same_week = [item for item in history["schedules"] if item.get("week_start") == week_start]
        # Older records without a version still count toward the sequence.
        record["version"] = max([len(same_week)] + [item.get("version", 0) for item in same_week]) + 1
        record["title"] = f"Lịch {record['date_range']} · Phiên bản {record['version']}"
        history["schedules"].append(record)
        _write_history_document(destination, history)

    return record
