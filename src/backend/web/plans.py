from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, time, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.state_codec import base_of, blocks_and_events, dump_state, load_planning_session, ui_code
from conflict_resolver.ai.advisor import get_settings
from conflict_resolver.models import Policy
from conflict_resolver.planning import PlanningSession, context_from_snapshot
from conflict_resolver.presentation import describe_changes
from conflict_resolver.schedule_view import build_full_schedule
from schedule_preparation.ui_adapter import snapshot_to_raw
from scheduling_algorithm.core_algorithm.history import build_history_record, number_history_record
from user_portal.metrics import compute_schedule_metrics, schedule_key
from user_portal.repository import record_finalized

from .auth import Session, planner
from .draft import check_revision, export_file, load_draft, require_valid
from .errors import WebError, not_found, stale
from .storage import database, encode

router = APIRouter(prefix="/plans", tags=["plans"])
Language = Literal["vi", "en"]


class CreatePlan(BaseModel):
    expected_revision: int = Field(ge=0)
    operation_id: UUID
    earlier: int = Field(default=0, ge=0, le=60)
    later: int = Field(default=0, ge=0, le=60)


class ConflictRequest(BaseModel):
    task_id: str
    expected_version: int = Field(ge=0)


class VersionedOperation(BaseModel):
    expected_version: int = Field(ge=0)
    operation_id: UUID


class ApplyRequest(VersionedOperation):
    task_id: str
    option_id: Literal[1, 2, 3]
    duration: int | None = Field(default=None, ge=1)


def stored_plan(conn, user_id, plan_id):
    row = conn.execute("SELECT * FROM web_plans WHERE user_id=? AND id=?", (user_id, plan_id)).fetchone()
    if row is None:
        raise not_found()
    return row, json.loads(row["state"])


def require_current(conn, user_id, row):
    revision = conn.execute("SELECT revision FROM web_drafts WHERE user_id=?", (user_id,)).fetchone()
    if row["draft_revision"] != (revision["revision"] if revision else 0):
        raise stale()


def verify_version(state, expected):
    if state["context"]["schedule_version"] != expected:
        raise stale()


def cached_operation(conn, user_id, operation_id, kind, request):
    row = conn.execute("SELECT kind,payload FROM web_operations WHERE user_id=? AND operation_id=?",
                       (user_id, str(operation_id))).fetchone()
    if not row:
        return None
    cached = json.loads(row["payload"])
    if row["kind"] != kind or cached["request"] != request:
        raise WebError(409, "OPERATION_REUSED", "Mã thao tác đã được dùng.")
    return cached["result"]


def save_operation(conn, user_id, operation_id, kind, request, result):
    conn.execute("INSERT INTO web_operations VALUES (?,?,?,?)",
                 (user_id, str(operation_id), kind, encode({"request": request, "result": result})))


def localized_events(week, entries, windows, state, lang):
    events = []
    for block, event in blocks_and_events(week, entries, windows, {**state, "lang": lang}):
        task_id = ui_code(block.ref_id, state.get("fixed_ui_ids", {}))
        event["extendedProps"] = {"task_id": task_id, "kind": block.kind}
        events.append(event)
    return events


def plan_view(plan_id, revision, state, lang, finalized=False):
    restored = load_planning_session(state)
    result, context = restored.cached_plan, restored.context
    week = date.fromisoformat(state["week_start"])
    entries = build_full_schedule(context, result.chunks)
    names = {task.id: task.name for task in context.tasks}
    reports = {}
    for task_id, (report, _) in restored.reports.items():
        options = []
        for option in report.options:
            options.append({
                "id": option.option_id,
                "available": option.is_available,
                "reason": option.unavailable_reason,
                "descriptions": describe_changes(option, context, state["week_start"]),
                "warnings": option.warnings,
                "minimum": next(task.min_remaining_min for task in context.tasks if task.id == task_id)
                if option.option_id == 2 and option.is_available else None,
                "maximum": option.action_payload.get("new_duration"),
                "explanation": option.ai_description if report.ai_status == "SUCCESS" else None,
                "unplaced": [{"name": names.get(key, key), "minutes": minutes} for key, minutes in option.unplaced.items()],
                "events": localized_events(week, option.full_schedule, option.active_windows, state, lang)
                if option.is_available else [],
            })
        reports[task_id] = {"options": options, "ai_status": report.ai_status}
    key = schedule_key(state["context"], state["result"], state["week_start"])
    origin = datetime.combine(week, time.min)
    return {
        "id": plan_id, "draft_revision": revision, "version": context.schedule_version, "week_start": week,
        "status": result.status, "optimal": result.proven_optimal, "earlier": context.policy.max_earlier_minutes,
        "later": context.policy.max_later_minutes, "schedule_key": key if finalized else None,
        "events": localized_events(week, entries, context.active_windows, state, lang),
        "deadline_details": {
            task.id: {"deadline": (origin + timedelta(minutes=task.deadline)).isoformat(timespec="minutes"),
                      "importance": task.importance, "mandatory": task.mandatory, "remaining_min": task.remaining_min}
            for task in context.tasks
        },
        "unscheduled": [{"id": key, "name": names.get(key, key), "minutes": minutes}
                        for key, minutes in result.unscheduled.items()],
        "reports": reports, "applied": state["applied"],
    }


def present(user_id, plan_id, revision, state, lang):
    key = schedule_key(state["context"], state["result"], state["week_start"])
    with database() as conn:
        finalized = conn.execute(
            "SELECT 1 FROM finalized_schedules WHERE user_id=? AND schedule_key=?", (user_id, key)
        ).fetchone()
    return plan_view(plan_id, revision, state, lang, bool(finalized))


@router.get("/latest")
def latest(lang: Language = "vi", current: Session = Depends(planner)):
    with database() as conn:
        draft = load_draft(conn, current.user.id)
        row = conn.execute(
            """SELECT * FROM web_plans WHERE user_id=? AND draft_revision=?
               ORDER BY rowid DESC LIMIT 1""", (current.user.id, draft.revision)
        ).fetchone()
    if row:
        return present(current.user.id, row["id"], row["draft_revision"], json.loads(row["state"]), lang)
    return None


@router.post("", status_code=201)
def create(data: CreatePlan, lang: Language = "vi", current: Session = Depends(planner)):
    user_id = current.user.id
    request = data.model_dump(mode="json")
    with database() as conn:
        prior = cached_operation(conn, user_id, data.operation_id, "plan", request)
        if prior:
            row, state = stored_plan(conn, user_id, prior)
            return present(user_id, prior, row["draft_revision"], state, lang)
        draft = load_draft(conn, user_id)
    check_revision(draft, data.expected_revision)
    require_valid(draft.service.review())
    snapshot = draft.service.confirm()
    contents = snapshot.to_dict()
    _, meta = snapshot_to_raw(snapshot)
    policy = Policy(max_earlier_minutes=data.earlier, max_later_minutes=data.later)
    engine = PlanningSession(context_from_snapshot(snapshot, policy))
    result = engine.plan()
    state = dump_state(engine, result, {
        "week_start": contents["window"]["week_start"],
        "input_snapshot": contents, "deadline_order": contents["deadline_tasks"],
        "fixed_ui_ids": meta.fixed_ui_ids,
        "fixed_colors": {ref: draft.colors[task] for ref, task in meta.fixed_ui_ids.items() if task in draft.colors},
        "applied": [],
    })
    plan_id = str(uuid4())
    with database(write=True) as conn:
        prior = cached_operation(conn, user_id, data.operation_id, "plan", request)
        if prior:
            plan_id = prior
            _, state = stored_plan(conn, user_id, plan_id)
        else:
            check_revision(load_draft(conn, user_id), data.expected_revision)
            conn.execute("INSERT INTO web_plans VALUES (?,?,?,?)",
                         (plan_id, user_id, draft.revision, encode(state)))
            save_operation(conn, user_id, data.operation_id, "plan", request, plan_id)
    return present(user_id, plan_id, draft.revision, state, lang)


@router.get("/{plan_id}")
def detail(plan_id: UUID, lang: Language = "vi", current: Session = Depends(planner)):
    with database() as conn:
        row, state = stored_plan(conn, current.user.id, str(plan_id))
    return present(current.user.id, str(plan_id), row["draft_revision"], state, lang)


@router.get("/{plan_id}/snapshot")
def snapshot(plan_id: UUID, current: Session = Depends(planner)):
    with database() as conn:
        _, state = stored_plan(conn, current.user.id, str(plan_id))
    return export_file(encode(state["input_snapshot"]), "input_snapshot.json", "application/json")


@router.post("/{plan_id}/conflicts")
def analyze(plan_id: UUID, data: ConflictRequest, lang: Language = "vi", current: Session = Depends(planner)):
    user_id, plan_id = current.user.id, str(plan_id)
    with database() as conn:
        row, state = stored_plan(conn, user_id, plan_id)
        require_current(conn, user_id, row)
    verify_version(state, data.expected_version)
    engine = load_planning_session(state)
    asyncio.run(engine.analyze(data.task_id, get_settings()))
    report, scoped = engine.reports[data.task_id]
    # Keep analyses for other targets that completed while solving this target.
    with database(write=True) as conn:
        current_row, current_state = stored_plan(conn, user_id, plan_id)
        require_current(conn, user_id, current_row)
        verify_version(current_state, data.expected_version)
        latest = load_planning_session(current_state)
        latest.reports[data.task_id] = (report, scoped)
        state = dump_state(latest, latest.cached_plan, base_of(current_state))
        conn.execute("UPDATE web_plans SET state=? WHERE id=?", (encode(state), plan_id))
    return present(user_id, plan_id, row["draft_revision"], state, lang)


@router.post("/{plan_id}/apply")
def apply(plan_id: UUID, data: ApplyRequest, lang: Language = "vi", current: Session = Depends(planner)):
    user_id, plan_id = current.user.id, str(plan_id)
    request = {**data.model_dump(mode="json"), "plan_id": plan_id}
    with database() as conn:
        row, state = stored_plan(conn, user_id, plan_id)
        prior = cached_operation(conn, user_id, data.operation_id, "apply", request)
        if prior:
            return present(user_id, plan_id, row["draft_revision"], prior, lang)
        require_current(conn, user_id, row)
    verify_version(state, data.expected_version)
    engine = load_planning_session(state)
    if data.task_id not in engine.reports:
        raise WebError(409, "ANALYSIS_REQUIRED", "Hãy phân tích phương án trước khi áp dụng.")
    report, _ = engine.reports[data.task_id]
    option = next((value for value in report.options if value.option_id == data.option_id), None)
    if option is None or not option.is_available or (data.option_id != 2 and data.duration is not None):
        raise WebError(422, "OPTION_INVALID", "Phương án không khả dụng.")
    task = next(task for task in engine.context.tasks if task.id == data.task_id)
    result = engine.apply(data.task_id, data.option_id, data.expected_version, data.duration)
    action = dict(option.action_payload)
    if data.option_id == 2 and data.duration is not None:
        action["new_duration"] = data.duration
    applied = {
        "source": "conflict_option", "target_task_id": task.id, "target_task_name": task.name,
        "option_id": data.option_id, "duration_min": action.get("new_duration"), "action_payload": action,
        "schedule_version": engine.context.schedule_version,
    }
    updated = dump_state(engine, result, {**base_of(state), "applied": [*state["applied"], applied]})
    with database(write=True) as conn:
        prior = cached_operation(conn, user_id, data.operation_id, "apply", request)
        if prior:
            updated = prior
        else:
            current_row, current_state = stored_plan(conn, user_id, plan_id)
            require_current(conn, user_id, current_row)
            verify_version(current_state, data.expected_version)
            conn.execute("UPDATE web_plans SET state=? WHERE id=?", (encode(updated), plan_id))
            save_operation(conn, user_id, data.operation_id, "apply", request, updated)
    return present(user_id, plan_id, row["draft_revision"], updated, lang)


def history_record(state):
    return build_history_record(
        context=state["context"], result=state["result"], week_start=state["week_start"],
        selection={"source": "conflict_options" if state["applied"] else "initial_schedule",
                   "applied_options": state["applied"]},
        input_snapshot=state["input_snapshot"],
    )


def insert_history(conn, user_id, record):
    rows = conn.execute("SELECT record FROM web_history WHERE user_id=? AND week_start=?",
                        (user_id, record["week_start"]))
    number_history_record(record, [json.loads(row["record"]) for row in rows])
    conn.execute("INSERT INTO web_history VALUES (?,?,?,?)",
                 (user_id, record["id"], record["week_start"], encode(record)))
    return record


@router.post("/{plan_id}/history", status_code=201)
def save_history(plan_id: UUID, data: VersionedOperation, current: Session = Depends(planner)):
    user_id, plan_id = current.user.id, str(plan_id)
    request = {**data.model_dump(mode="json"), "plan_id": plan_id}
    with database(write=True) as conn:
        prior = cached_operation(conn, user_id, data.operation_id, "history", request)
        if prior:
            return prior
        row, state = stored_plan(conn, user_id, plan_id)
        require_current(conn, user_id, row)
        verify_version(state, data.expected_version)
        record = insert_history(conn, user_id, history_record(state))
        save_operation(conn, user_id, data.operation_id, "history", request, record)
        return record


class Finalize(BaseModel):
    expected_version: int = Field(ge=0)


def finalize_state(conn, user_id, plan_id, expected_version):
    row, state = stored_plan(conn, user_id, plan_id)
    require_current(conn, user_id, row)
    verify_version(state, expected_version)
    metrics = compute_schedule_metrics(state["context"], state["result"], state["applied"])
    key = schedule_key(state["context"], state["result"], state["week_start"])
    record_finalized(user_id, key, state["week_start"], metrics["complete"], bool(metrics["options_applied"]), conn=conn)
    conn.execute("INSERT OR IGNORE INTO web_finalized VALUES (?,?,?,?)",
                 (user_id, key, state["week_start"], encode(metrics)))
    return key, state


@router.post("/{plan_id}/finalize")
def finalize(plan_id: UUID, data: Finalize, current: Session = Depends(planner)):
    with database(write=True) as conn:
        key, _ = finalize_state(conn, current.user.id, str(plan_id), data.expected_version)
    return {"schedule_key": key}


@router.post("/{plan_id}/download")
def download(plan_id: UUID, data: Finalize, current: Session = Depends(planner)):
    with database(write=True) as conn:
        key, state = finalize_state(conn, current.user.id, str(plan_id), data.expected_version)
    record = history_record(state)
    return export_file(encode({**record, "schedule_key": key}), f"schedule_{state['week_start']}.json", "application/json")
