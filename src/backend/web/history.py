from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Response

from conflict_resolver.models import Interval, ScheduleEntry
from scheduling_algorithm.core_algorithm.history_input import input_from_history

from .auth import Session, planner
from .draft import ChangeBase, check_revision, describe, export_file, load_draft, save_draft
from .errors import not_found
from . import mysql_sync
from .plans import Language, localized_events
from .storage import database, encode

router = APIRouter(prefix="/history", tags=["history"])
SUMMARY = ("id", "week_start", "version", "title", "description", "saved_at", "complete")


def owned_record(conn, user_id, record_id):
    row = conn.execute("SELECT record FROM web_history WHERE user_id=? AND id=?",
                       (user_id, record_id)).fetchone()
    if not row:
        raise not_found()
    return json.loads(row["record"])


def history_view(record, lang):
    context, result = record["context"], record["result"]
    names = {task["id"]: task["name"] for task in context["tasks"]}
    entries = [
        ScheduleEntry(kind="TASK", ref_id=chunk["task_id"], name=names.get(chunk["task_id"], chunk["task_id"]),
                      start=chunk["start"], end=chunk["end"], buffer_end=chunk.get("buffer_end", chunk["end"]))
        for chunk in result.get("chunks", [])
    ]
    entries.extend(
        ScheduleEntry(kind="FIXED", ref_id=item["id"], name=item["name"], start=item["interval"]["start"],
                      end=item["interval"]["end"], ancillary=item.get("ancillary", False))
        for item in context.get("fixed_tasks", [])
    )
    entries.sort(key=lambda entry: (entry.start, entry.end, entry.ref_id))
    windows = [Interval.model_validate(value) for value in context.get("active_windows", [])]
    order = [{"importance": 2, **task} for task in context["tasks"]]
    week = date.fromisoformat(record["week_start"])
    origin = datetime.combine(week, time.min)
    return {
        "record": record,
        "events": localized_events(week, entries, windows, {"deadline_order": order}, lang),
        "entries": [
            {"name": entry.name, "kind": "deadline" if entry.kind == "TASK" else "reserve" if entry.ancillary else "fixed",
             "start": (origin + timedelta(minutes=entry.start)).isoformat(timespec="minutes"),
             "end": (origin + timedelta(minutes=entry.end)).isoformat(timespec="minutes")}
            for entry in entries
        ],
    }


@router.get("")
def list_records(week_start: date | None = None, current: Session = Depends(planner)):
    with database() as conn:
        rows = conn.execute(
            """SELECT record FROM web_history WHERE user_id=? AND (? IS NULL OR week_start=?)
               ORDER BY week_start DESC, rowid DESC""", (current.user.id, week_start, week_start)
        ).fetchall()
    return [{key: record.get(key) for key in SUMMARY} for row in rows if (record := json.loads(row["record"]))]


@router.get("/{record_id}")
def detail(record_id: str, lang: Language = "vi", current: Session = Depends(planner)):
    with database() as conn:
        record = owned_record(conn, current.user.id, record_id)
    return history_view(record, lang)


@router.get("/{record_id}/export")
def export(record_id: str, current: Session = Depends(planner)):
    with database() as conn:
        record = owned_record(conn, current.user.id, record_id)
    week = date.fromisoformat(record["week_start"])
    version = record.get("version")
    suffix = version if isinstance(version, int) else "old"
    return export_file(encode(record), f"schedule_{week}_v{suffix}.json", "application/json")


@router.delete("/{record_id}", status_code=204)
def delete(record_id: str, current: Session = Depends(planner)):
    with database(write=True) as conn:
        deleted = conn.execute("DELETE FROM web_history WHERE user_id=? AND id=?", (current.user.id, record_id))
        if not deleted.rowcount:
            raise not_found()
    mysql_sync.sync_history_deleted(current.user.id, record_id)
    return Response(status_code=204)


@router.post("/{record_id}/restore")
def restore(record_id: str, data: ChangeBase, current: Session = Depends(planner)):
    with database(write=True) as conn:
        record = owned_record(conn, current.user.id, record_id)
        draft = load_draft(conn, current.user.id, for_update=True)
        check_revision(draft, data.expected_revision)
        previous = draft.saved_data()
        candidate, notes = input_from_history(record)
        draft.service.data = candidate
        draft.service.now_override = candidate.window.now
        draft.colors = {key: value for key, value in draft.colors.items() if key in candidate._tasks}
        draft.notes = notes
        save_draft(conn, current.user.id, draft, previous)
    mysql_sync.sync_draft(current.user.id, draft.service.data, draft.colors)
    return describe(draft)
