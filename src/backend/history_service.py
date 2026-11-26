"""Lịch sử các phiên bản lịch (bảng schedule_histories) — thay schedule_history.json cũ."""
from __future__ import annotations

import copy
import json
import uuid
from datetime import date, datetime, timedelta, timezone

from scheduling_algorithm.core_algorithm.history import _schedule_metadata

from .clock import lenient_now
from .db import db_readonly, db_transaction
from .errors import BackendError, InputInvalidError, NotFoundError
from .input_builder import build_schedule_input_from_core
from .mysql_task_repo import MySQLTaskRepository, save_week_settings
from .state_codec import block_row_to_event

_LOCAL_TZ = timezone(timedelta(hours=7), name="Asia/Saigon")


def insert_history(cur, user_id: int, schedule_id: int, week_start: date, state: dict,
                   selection: dict, save_source: str):
    """Ghi 1 phiên bản vào schedule_histories TRONG transaction của người gọi.
    Trả (history_id, version, title, description)."""
    meta = _schedule_metadata(copy.deepcopy(state["context"]), copy.deepcopy(state["result"]),
                              copy.deepcopy(selection), week_start)
    cur.execute("SELECT COALESCE(MAX(version), 0) + 1 AS v FROM schedule_histories "
                "WHERE user_id=%s AND week_start=%s FOR UPDATE", (user_id, week_start))
    version = int(cur.fetchone()["v"])
    title = f"Lịch {meta['date_range']} · Phiên bản {version}"
    result = state["result"]
    complete = result["status"] == "FEASIBLE" and not result.get("unscheduled")
    history_uuid = str(uuid.uuid4())
    now_utc = datetime.now(timezone.utc)
    local = now_utc.astimezone(_LOCAL_TZ)
    record = {
        "id": history_uuid, "saved_at": now_utc.isoformat(), "saved_at_local": local.isoformat(),
        "saved_at_display": local.strftime("%d/%m/%Y %H:%M:%S"), "timezone": "Asia/Saigon",
        "week_start": week_start.isoformat(), "time_unit": "minutes",
        "time_origin": "week_start_00:00", "complete": complete,
        "selection": selection, "context": state["context"], "result": state["result"],
        **meta, "version": version, "title": title,
    }
    record_json = json.dumps(record, ensure_ascii=False, allow_nan=False)
    cur.execute(
        "INSERT INTO schedule_histories (history_uuid, user_id, schedule_id, week_start, week_end, "
        "version, title, description, save_source, creation_method, is_complete, "
        "applied_options_json, input_snapshot_json, frozen_record_json) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (history_uuid, user_id, schedule_id, week_start, date.fromisoformat(meta["week_end"]),
         version, title, meta["description"], save_source, meta["creation_method"],
         1 if complete else 0,
         json.dumps(meta["applied_options"], ensure_ascii=False),
         json.dumps(state.get("input"), ensure_ascii=False), record_json))
    return cur.lastrowid, version, title, meta["description"]


def save_manual_history(user_id: int, schedule_id: int) -> dict:
    """Nút "Lưu lịch hiện tại vào history". Đã có bản cho lịch này thì trả lại bản đó."""
    with db_transaction() as cur:
        cur.execute("SELECT week_start, solver_state_json FROM schedules "
                    "WHERE id=%s AND user_id=%s FOR UPDATE", (schedule_id, int(user_id)))
        sched = cur.fetchone()
        if not sched:
            raise NotFoundError()
        cur.execute("SELECT id, version, title, description FROM schedule_histories "
                    "WHERE schedule_id=%s AND user_id=%s ORDER BY version DESC LIMIT 1",
                    (schedule_id, int(user_id)))
        existing = cur.fetchone()
        if existing:
            return {"history_id": existing["id"], "version": existing["version"],
                    "title": existing["title"], "description": existing["description"],
                    "created": False}
        state = json.loads(sched["solver_state_json"])
        selection = {"source": "manual_save", "applied_options": state.get("applied_options", [])}
        history_id, version, title, description = insert_history(
            cur, int(user_id), schedule_id, sched["week_start"], state, selection, "manual_save")
    return {"history_id": history_id, "version": version, "title": title,
            "description": description, "created": True}


def _summary(row: dict) -> dict:
    return {
        "history_id": row["id"], "schedule_id": row["schedule_id"],
        "week_start": row["week_start"].isoformat(), "week_end": row["week_end"].isoformat(),
        "version": row["version"], "title": row["title"], "description": row["description"],
        "save_source": row["save_source"], "creation_method": row["creation_method"],
        "is_complete": bool(row["is_complete"]), "user_note": row["user_note"],
        "is_pinned": bool(row["is_pinned"]), "saved_at": row["saved_at"].isoformat(),
    }


def list_histories(user_id: int, week_start: date | None = None) -> list[dict]:
    sql = ("SELECT id, schedule_id, week_start, week_end, version, title, description, save_source, "
           "creation_method, is_complete, user_note, is_pinned, saved_at, "
           "EXISTS(SELECT 1 FROM feedbacks f WHERE f.schedule_id = h.schedule_id "
           "AND f.user_id = h.user_id) AS has_feedback "
           "FROM schedule_histories h WHERE user_id=%s")
    params: list = [int(user_id)]
    if week_start is not None:
        sql += " AND week_start=%s"
        params.append(week_start)
    sql += " ORDER BY week_start DESC, version DESC"
    with db_readonly() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [{**_summary(r), "has_feedback": bool(r["has_feedback"])} for r in rows]


def get_history_detail(user_id: int, history_id: int, include_frozen: bool = False) -> dict:
    with db_readonly() as cur:
        cur.execute("SELECT * FROM schedule_histories WHERE id=%s AND user_id=%s",
                    (history_id, int(user_id)))
        row = cur.fetchone()
        if not row:
            raise NotFoundError()
        cur.execute("SELECT id, block_kind, ref_task_code, title, start_datetime, end_datetime, "
                    "bg_color, text_color FROM schedule_blocks WHERE schedule_id=%s "
                    "ORDER BY start_datetime, end_datetime, id", (row["schedule_id"],))
        blocks = cur.fetchall()
        cur.execute("SELECT unscheduled_json FROM schedules WHERE id=%s", (row["schedule_id"],))
        sched = cur.fetchone()
    detail = {**_summary(row), "events": [block_row_to_event(b) for b in blocks],
              "unscheduled": json.loads(sched["unscheduled_json"] or "[]") if sched else [],
              "applied_options": json.loads(row["applied_options_json"] or "[]"),
              "has_input_snapshot": bool(row["input_snapshot_json"]
                                         and row["input_snapshot_json"] != "null")}
    if include_frozen:
        detail["frozen_record"] = json.loads(row["frozen_record_json"])
    return detail


def get_history_download(user_id: int, history_id: int) -> tuple[str, str]:
    """(tên_file, nội_dung_json) cho nút "Tải phiên bản lịch này (JSON)"."""
    with db_readonly() as cur:
        cur.execute("SELECT week_start, version, frozen_record_json FROM schedule_histories "
                    "WHERE id=%s AND user_id=%s", (history_id, int(user_id)))
        row = cur.fetchone()
    if not row:
        raise NotFoundError()
    record = json.loads(row["frozen_record_json"])
    return (f"schedule_{row['week_start'].isoformat()}_v{row['version']}.json",
            json.dumps(record, ensure_ascii=False, indent=2))


def update_history_meta(user_id: int, history_id: int, note: str | None = None,
                        pinned: bool | None = None) -> None:
    """Ghi chú (tối đa 255 ký tự) và ghim phiên bản. Tham số None = giữ nguyên."""
    sets, params = [], []
    if note is not None:
        sets.append("user_note=%s")
        params.append(note.strip()[:255] or None)
    if pinned is not None:
        sets.append("is_pinned=%s")
        params.append(1 if pinned else 0)
    if not sets:
        return
    with db_transaction() as cur:
        cur.execute(f"UPDATE schedule_histories SET {', '.join(sets)} WHERE id=%s AND user_id=%s",
                    (*params, history_id, int(user_id)))
        if cur.rowcount == 0:
            cur.execute("SELECT id FROM schedule_histories WHERE id=%s AND user_id=%s",
                        (history_id, int(user_id)))
            if not cur.fetchone():
                raise NotFoundError()


def delete_history(user_id: int, history_id: int) -> None:
    with db_transaction() as cur:
        cur.execute("DELETE FROM schedule_histories WHERE id=%s AND user_id=%s",
                    (history_id, int(user_id)))
        if cur.rowcount == 0:
            raise NotFoundError()


def restore_history_input(user_id: int, history_id: int) -> dict:
    """Ghi lại dữ liệu nhập (việc cố định, deadline, giờ ngủ) của phiên bản này vào tuần đó."""
    with db_readonly() as cur:
        cur.execute("SELECT week_start, input_snapshot_json FROM schedule_histories "
                    "WHERE id=%s AND user_id=%s", (history_id, int(user_id)))
        row = cur.fetchone()
    if not row:
        raise NotFoundError()
    snapshot = json.loads(row["input_snapshot_json"]) if row["input_snapshot_json"] else None
    if not snapshot:
        raise BackendError("Phiên bản này không lưu kèm dữ liệu nhập nên không khôi phục được.")
    week_start = row["week_start"]
    data, issues = build_schedule_input_from_core(
        week_start, snapshot["settings"], snapshot["fixed_tasks"], snapshot["deadline_tasks"],
        lenient_now(week_start))
    if issues:
        raise InputInvalidError([i if isinstance(i, dict) else
                                 {"code": i.code, "severity": i.severity.value, "field": i.field,
                                  "task_code": i.task_id, "message": i.message} for i in issues])
    colors = {f["id"]: f["display_color"] for f in snapshot["fixed_tasks"] if f.get("display_color")}
    MySQLTaskRepository(user_id, week_start).save(data, None, colors)
    s = snapshot["settings"]
    save_week_settings(user_id, week_start, max_earlier_min=s.get("max_earlier_min"),
                       max_later_min=s.get("max_later_min"))
    return {"week_start": week_start.isoformat(), "fixed_tasks": len(data.fixed_tasks),
            "deadline_tasks": len(data.deadline_tasks)}
