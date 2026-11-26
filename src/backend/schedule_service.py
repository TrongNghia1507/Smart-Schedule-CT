"""Điều phối xếp lịch, phân tích và áp dụng phương án conflict.

Quy tắc: không bao giờ giữ transaction / kết nối DB mở trong lúc CP-SAT hay AI đang chạy.
Đọc -> đóng kết nối -> tính trong RAM -> mở transaction mới để ghi.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
from datetime import date

from conflict_resolver.ai.advisor import get_settings
from conflict_resolver.models import PlanResult
from conflict_resolver.planning import PlanningSession
from conflict_resolver.presentation import describe_changes
from conflict_resolver.schedule_view import build_full_schedule

from .clock import effective_planning_now, lenient_now
from .db import db_readonly, db_transaction
from .errors import (AlreadyAppliedError, InvalidWeekError, NotFoundError,
                     OptionNotApplicableError, StaleVersionError, TaskNotUnscheduledError,
                     BackendError)
from .history_service import insert_history
from .input_builder import (build_context, core_inputs, fetch_week_rows, input_hash,
                            settings_dict, validate_rows)
from .mysql_task_repo import save_week_settings
from .state_codec import (base_of, block_insert_rows, block_row_to_event, blocks_and_events,
                          dump_state, load_planning_session)

OPTION_TITLES = {1: "Bỏ task khỏi tuần", 2: "Giảm thời lượng task", 3: "Nới ràng buộc"}


# ------------------------------------------------------------------ tiện ích
def _check_monday(week_start: date) -> None:
    if week_start.weekday() != 0:
        raise InvalidWeekError()


def _run_async(coro):
    """Chạy coroutine từ code đồng bộ, kể cả khi đang có event loop (Streamlit/Jupyter)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _unscheduled_list(context, unscheduled: dict) -> list[dict]:
    by_id = {t.id: t for t in context.tasks}
    out = []
    for task_id, minutes in unscheduled.items():
        task = by_id.get(task_id)
        out.append({"task_code": task_id, "name": task.name if task else task_id,
                    "missing_minutes": int(minutes),
                    "mandatory": bool(task.mandatory) if task else False,
                    "importance": int(task.importance) if task else 2})
    return out


def _load_schedule(cur, user_id: int, schedule_id: int, for_update: bool = False) -> dict:
    cur.execute("SELECT * FROM schedules WHERE id=%s AND user_id=%s" +
                (" FOR UPDATE" if for_update else ""), (schedule_id, int(user_id)))
    row = cur.fetchone()
    if not row:
        raise NotFoundError()
    return row


def _insert_schedule(cur, *, user_id: int, week_start: date, session: PlanningSession,
                     result: PlanResult, state: dict, pairs: list, parent_id: int | None = None,
                     creation_source: str = "cp_sat", applied_option_id: int | None = None,
                     input_hash_value: str | None = None) -> int:
    context = session.context
    unscheduled = _unscheduled_list(context, result.unscheduled)
    cur.execute(
        "INSERT INTO schedules (user_id, parent_schedule_id, week_start, schedule_version, status, "
        "proven_optimal, creation_source, applied_option_id, total_tasks, scheduled_tasks, "
        "unscheduled_tasks, unscheduled_json, input_hash, solver_state_json) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (user_id, parent_id, week_start, context.schedule_version, result.status,
         1 if result.proven_optimal else 0, creation_source, applied_option_id,
         len(context.tasks), len({c.task_id for c in result.chunks}), len(unscheduled),
         json.dumps(unscheduled, ensure_ascii=False), input_hash_value,
         json.dumps(state, ensure_ascii=False)))
    schedule_id = cur.lastrowid
    rows = block_insert_rows(schedule_id, pairs, state["fixed_ui_ids"])
    if rows:
        cur.executemany(
            "INSERT INTO schedule_blocks (schedule_id, block_kind, ref_task_code, title, "
            "start_datetime, end_datetime, bg_color, text_color) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            rows)
    return schedule_id


# ---------------------------------------------------------- cài đặt / kiểm tra
def update_policy_settings(user_id: int, week_start: date, max_earlier_min: int,
                           max_later_min: int) -> dict:
    """Mức cho phép dậy sớm / ngủ muộn (0..60 phút) dùng cho Option 3."""
    return save_week_settings(user_id, week_start, max_earlier_min=max_earlier_min,
                              max_later_min=max_later_min)


def validate_week(user_id: int, week_start: date) -> dict:
    """{'issues': [...], 'has_errors': bool, 'free_minutes': int} cho huy hiệu lỗi/cảnh báo."""
    _check_monday(week_start)
    with db_readonly() as cur:
        settings, fixed_rows, deadline_rows = fetch_week_rows(cur, int(user_id), week_start)
    return validate_rows(week_start, settings, fixed_rows, deadline_rows, lenient_now(week_start))


# ------------------------------------------------------------------ xếp lịch
def run_schedule(user_id: int, week_start: date, lang: str = "vi") -> dict:
    """Đọc dữ liệu nhập của (user, tuần), chạy CP-SAT, ghi schedules + schedule_blocks.

    Ném: WeekAlreadyOverError, InputInvalidError, CannotPlanError,
    conflict_resolver.errors.SolverInconclusive (UI nên cho bấm "Thử lại").
    """
    user_id = int(user_id)
    _check_monday(week_start)
    now = effective_planning_now(week_start)
    with db_readonly() as cur:
        settings, fixed_rows, deadline_rows = fetch_week_rows(cur, user_id, week_start)

    built = build_context(week_start, settings, fixed_rows, deadline_rows, now)
    session = PlanningSession(built.context)
    result = session.plan()

    color_by_code = {r["task_code"]: r["display_color"] for r in fixed_rows if r["display_color"]}
    fixed_dicts, deadline_dicts = core_inputs(fixed_rows, deadline_rows, with_color=True)
    base = {
        "lang": lang,
        "week_start": week_start.isoformat(),
        "fixed_ui_ids": built.meta.fixed_ui_ids,
        "deadline_order": [{"id": t["id"], "importance": t["importance"]}
                           for t in built.snapshot["deadline_tasks"]],
        "fixed_colors": {ref: color_by_code[code] for ref, code in built.meta.fixed_ui_ids.items()
                         if code in color_by_code},
        "applied_options": [],
        "input": {"settings": settings_dict(settings), "fixed_tasks": fixed_dicts,
                  "deadline_tasks": deadline_dicts},
    }
    state = dump_state(session, result, base)
    pairs = blocks_and_events(week_start, build_full_schedule(session.context, result.chunks),
                              session.context.active_windows, state)
    with db_transaction() as cur:
        schedule_id = _insert_schedule(
            cur, user_id=user_id, week_start=week_start, session=session, result=result,
            state=state, pairs=pairs,
            input_hash_value=input_hash(settings, fixed_rows, deadline_rows))
    view = get_schedule_view(user_id, schedule_id)
    view["warnings"] = built.warnings
    return view


def get_schedule_view(user_id: int, schedule_id: int) -> dict:
    user_id = int(user_id)
    with db_readonly() as cur:
        cur.execute("SELECT id, parent_schedule_id, week_start, schedule_version, status, "
                    "proven_optimal, creation_source, applied_option_id, total_tasks, "
                    "scheduled_tasks, unscheduled_tasks, unscheduled_json, input_hash, created_at "
                    "FROM schedules WHERE id=%s AND user_id=%s", (schedule_id, user_id))
        row = cur.fetchone()
        if not row:
            raise NotFoundError()
        cur.execute("SELECT id, block_kind, ref_task_code, title, start_datetime, end_datetime, "
                    "bg_color, text_color FROM schedule_blocks WHERE schedule_id=%s "
                    "ORDER BY start_datetime, end_datetime, id", (schedule_id,))
        blocks = cur.fetchall()
        cur.execute("SELECT id FROM schedule_histories WHERE schedule_id=%s AND user_id=%s "
                    "ORDER BY version DESC LIMIT 1", (schedule_id, user_id))
        history = cur.fetchone()
        cur.execute("SELECT id FROM feedbacks WHERE schedule_id=%s AND user_id=%s",
                    (schedule_id, user_id))
        feedback = cur.fetchone()
        cur.execute("SELECT resulting_schedule_id FROM conflict_options WHERE schedule_id=%s "
                    "AND is_selected=1 LIMIT 1", (schedule_id,))
        applied = cur.fetchone()
        settings, fixed_rows, deadline_rows = fetch_week_rows(cur, user_id, row["week_start"])
    changed = bool(row["input_hash"]) and row["input_hash"] != input_hash(
        settings, fixed_rows, deadline_rows)
    return {
        "schedule_id": row["id"], "parent_schedule_id": row["parent_schedule_id"],
        "week_start": row["week_start"].isoformat(), "schedule_version": row["schedule_version"],
        "status": row["status"], "proven_optimal": bool(row["proven_optimal"]),
        "creation_source": row["creation_source"], "applied_option_id": row["applied_option_id"],
        "summary": {"total_tasks": row["total_tasks"], "scheduled_tasks": row["scheduled_tasks"],
                    "unscheduled_tasks": row["unscheduled_tasks"]},
        "unscheduled": json.loads(row["unscheduled_json"] or "[]"),
        "input_changed": changed, "has_feedback": feedback is not None,
        "history_id": history["id"] if history else None,
        "applied_to_schedule_id": applied["resulting_schedule_id"] if applied else None,
        "events": [block_row_to_event(b) for b in blocks],
        "created_at": row["created_at"].isoformat(),
    }


def get_latest_schedule(user_id: int, week_start: date) -> dict | None:
    with db_readonly() as cur:
        cur.execute("SELECT id FROM schedules WHERE user_id=%s AND week_start=%s "
                    "ORDER BY id DESC LIMIT 1", (int(user_id), week_start))
        row = cur.fetchone()
    return get_schedule_view(user_id, row["id"]) if row else None


def list_schedules(user_id: int, week_start: date | None = None) -> list[dict]:
    sql = ("SELECT id, parent_schedule_id, week_start, schedule_version, status, creation_source, "
           "applied_option_id, total_tasks, scheduled_tasks, unscheduled_tasks, created_at "
           "FROM schedules WHERE user_id=%s")
    params: list = [int(user_id)]
    if week_start is not None:
        sql += " AND week_start=%s"
        params.append(week_start)
    with db_readonly() as cur:
        cur.execute(sql + " ORDER BY id DESC", params)
        rows = cur.fetchall()
    return [{**r, "week_start": r["week_start"].isoformat(), "created_at": r["created_at"].isoformat()}
            for r in rows]


# ------------------------------------------------------------------- conflict
def _option_view(row: dict) -> dict:
    maximum = row["max_new_duration_min"]
    return {
        "option_code": row["option_code"], "title": OPTION_TITLES.get(row["option_code"], ""),
        "priority_rank": row["priority_rank"], "is_available": bool(row["is_available"]),
        "unavailable_reason": row["unavailable_reason"],
        "changes": [line for line in (row["changes_summary"] or "").split("\n") if line],
        "ai_status": row["ai_status"], "ai_explanation": row["ai_explanation"],
        "warnings": json.loads(row["warnings_json"] or "[]"),
        "still_unplaced": json.loads(row["unplaced_json"] or "[]"),
        "duration_slider": ({"min": 1, "max": maximum, "default": maximum} if maximum else None),
        "preview_events": json.loads(row["preview_blocks_json"] or "[]"),
        "is_selected": bool(row["is_selected"]),
        "chosen_duration_min": row["chosen_duration_min"],
        "resulting_schedule_id": row["resulting_schedule_id"],
    }


def get_conflict_options(user_id: int, schedule_id: int, target_task_code: str) -> dict:
    with db_readonly() as cur:
        cur.execute("SELECT co.* FROM conflict_options co JOIN schedules s ON s.id = co.schedule_id "
                    "WHERE co.schedule_id=%s AND s.user_id=%s AND co.target_task_code=%s "
                    "ORDER BY co.priority_rank, co.option_code",
                    (schedule_id, int(user_id), target_task_code))
        rows = cur.fetchall()
    if not rows:
        raise NotFoundError("Chưa phân tích phương án cho task này.")
    return {"schedule_id": schedule_id, "target_task_code": target_task_code,
            "target_task_name": rows[0]["target_task_name"], "deficit_min": rows[0]["deficit_min"],
            "ai_status": rows[0]["ai_status"], "options": [_option_view(r) for r in rows]}


def analyze_conflict(user_id: int, schedule_id: int, target_task_code: str,
                     refresh: bool = False) -> dict:
    """Tính 3 phương án (bỏ task / giảm thời lượng / nới ràng buộc) và lời giải thích AI."""
    user_id = int(user_id)
    with db_readonly() as cur:
        sched = _load_schedule(cur, user_id, schedule_id)
        cur.execute("SELECT 1 AS x FROM conflict_options WHERE schedule_id=%s AND is_selected=1 "
                    "LIMIT 1", (schedule_id,))
        selected = cur.fetchone()
        cur.execute("SELECT COUNT(*) AS n FROM conflict_options WHERE schedule_id=%s "
                    "AND target_task_code=%s", (schedule_id, target_task_code))
        cached = cur.fetchone()["n"]
    if sched["status"] != "NOT_FOUND":
        raise BackendError("Lịch này đã xếp đủ, không có xung đột cần xử lý.")
    if selected:
        raise AlreadyAppliedError("Lịch này đã áp dụng một phương án; hãy làm việc trên lịch mới.")
    state = json.loads(sched["solver_state_json"])
    if target_task_code not in state["result"].get("unscheduled", {}):
        raise TaskNotUnscheduledError("Task này đã được xếp hoặc không tồn tại.")
    if cached == 3 and not refresh:
        return get_conflict_options(user_id, schedule_id, target_task_code)

    session = load_planning_session(state)
    try:
        report = _run_async(session.analyze(target_task_code, get_settings()))
    except ValueError as exc:
        raise TaskNotUnscheduledError(str(exc)) from exc

    week_start = sched["week_start"]
    names = {t.id: t.name for t in session.context.tasks}
    option_rows = []
    for option in report.options:
        changes = describe_changes(option, session.context, week_start.isoformat())
        preview = None
        if option.is_available:
            pairs = blocks_and_events(week_start, option.full_schedule, option.active_windows, state)
            preview = json.dumps([event for _, event in pairs], ensure_ascii=False)
        maximum = (option.action_payload.get("new_duration")
                   if option.option_id == 2 and option.is_available else None)
        unplaced = [{"task_code": tid, "name": names.get(tid, tid), "missing_minutes": int(m)}
                    for tid, m in option.unplaced.items()]
        option_rows.append((
            schedule_id, target_task_code, names.get(target_task_code, target_task_code)[:100],
            max(0, int(report.deficit_minutes)), option.option_id, option.priority_rank,
            1 if option.is_available else 0,
            (option.unavailable_reason or None) and option.unavailable_reason[:255],
            "\n".join(changes), option.ai_description or None, report.ai_status, maximum,
            json.dumps(option.action_payload, ensure_ascii=False), preview,
            json.dumps(option.warnings, ensure_ascii=False),
            json.dumps(unplaced, ensure_ascii=False)))

    new_state = dump_state(session, session.cached_plan, base_of(state))
    with db_transaction() as cur:
        cur.execute("UPDATE schedules SET solver_state_json=%s WHERE id=%s AND user_id=%s",
                    (json.dumps(new_state, ensure_ascii=False), schedule_id, user_id))
        cur.executemany(
            "INSERT INTO conflict_options (schedule_id, target_task_code, target_task_name, "
            "deficit_min, option_code, priority_rank, is_available, unavailable_reason, "
            "changes_summary, ai_explanation, ai_status, max_new_duration_min, "
            "action_payload_json, preview_blocks_json, warnings_json, unplaced_json) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE target_task_name=VALUES(target_task_name), "
            "deficit_min=VALUES(deficit_min), priority_rank=VALUES(priority_rank), "
            "is_available=VALUES(is_available), unavailable_reason=VALUES(unavailable_reason), "
            "changes_summary=VALUES(changes_summary), ai_explanation=VALUES(ai_explanation), "
            "ai_status=VALUES(ai_status), max_new_duration_min=VALUES(max_new_duration_min), "
            "action_payload_json=VALUES(action_payload_json), "
            "preview_blocks_json=VALUES(preview_blocks_json), warnings_json=VALUES(warnings_json), "
            "unplaced_json=VALUES(unplaced_json)", option_rows)
    return get_conflict_options(user_id, schedule_id, target_task_code)


def apply_conflict_option(user_id: int, schedule_id: int, target_task_code: str,
                          option_code: int, chosen_duration_min: int | None = None,
                          expected_version: int | None = None) -> dict:
    """Áp dụng 1 phương án: kiểm chứng lại bằng CP-SAT, tạo lịch mới, đánh dấu lựa chọn và
    tự lưu 1 phiên bản history. Trả view của LỊCH MỚI (còn kẹt thì chọn task kẹt tiếp theo)."""
    user_id = int(user_id)
    with db_readonly() as cur:
        sched = _load_schedule(cur, user_id, schedule_id)
        cur.execute("SELECT 1 AS x FROM conflict_options WHERE schedule_id=%s AND is_selected=1 "
                    "LIMIT 1", (schedule_id,))
        selected = cur.fetchone()
        cur.execute("SELECT * FROM conflict_options WHERE schedule_id=%s AND target_task_code=%s "
                    "AND option_code=%s", (schedule_id, target_task_code, option_code))
        option_row = cur.fetchone()
    if selected:
        raise AlreadyAppliedError("Lịch này đã áp dụng một phương án.")
    if not option_row:
        raise OptionNotApplicableError("Hãy phân tích phương án trước khi áp dụng.")
    if not option_row["is_available"]:
        raise OptionNotApplicableError("Phương án này không khả dụng.")
    if expected_version is not None and expected_version != sched["schedule_version"]:
        raise StaleVersionError("Lịch đã đổi; hãy phân tích lại conflict.")

    duration = None
    if option_code == 2:
        maximum = int(option_row["max_new_duration_min"] or 0)
        duration = maximum if chosen_duration_min is None else chosen_duration_min
        if isinstance(duration, bool) or not isinstance(duration, int) or not 1 <= duration <= maximum:
            raise OptionNotApplicableError(f"Thời lượng mới phải từ 1 đến {maximum} phút.")

    state = json.loads(sched["solver_state_json"])
    session = load_planning_session(state)
    if target_task_code not in session.reports:
        raise OptionNotApplicableError("Cần phân tích lại phương án (dữ liệu phân tích đã cũ).")
    report, _ = session.reports[target_task_code]
    option = next((o for o in report.options if o.option_id == option_code), None)
    if option is None or not option.is_available:
        raise OptionNotApplicableError("Phương án này không khả dụng.")
    target_name = next((t.name for t in session.context.tasks if t.id == target_task_code),
                       target_task_code)
    try:
        new_result = session.apply(target_task_code, option_code, sched["schedule_version"], duration)
    except ValueError as exc:
        raise OptionNotApplicableError(str(exc)) from exc  # SolverInconclusive được giữ nguyên

    chosen_action = dict(option.action_payload)
    if option_code == 2 and duration is not None:
        chosen_action["new_duration"] = duration
    selected_option = {
        "source": "conflict_option", "target_task_id": target_task_code,
        "target_task_name": target_name, "option_id": option_code, "duration_min": duration,
        "action_payload": chosen_action, "schedule_version": session.context.schedule_version,
    }
    applied = list(state.get("applied_options", [])) + [selected_option]
    new_base = {**base_of(state), "applied_options": applied}
    new_state = dump_state(session, new_result, new_base)
    week_start = sched["week_start"]
    pairs = blocks_and_events(week_start, build_full_schedule(session.context, new_result.chunks),
                              session.context.active_windows, new_state)

    with db_transaction() as cur:
        _load_schedule(cur, user_id, schedule_id, for_update=True)  # tuần tự hóa các lần bấm
        cur.execute("SELECT 1 AS x FROM conflict_options WHERE schedule_id=%s AND is_selected=1 "
                    "LIMIT 1", (schedule_id,))
        if cur.fetchone():
            raise AlreadyAppliedError("Lịch này đã áp dụng một phương án.")
        new_id = _insert_schedule(
            cur, user_id=user_id, week_start=week_start, session=session, result=new_result,
            state=new_state, pairs=pairs, parent_id=schedule_id,
            creation_source="conflict_option", applied_option_id=option_code,
            input_hash_value=sched["input_hash"])
        cur.execute("UPDATE conflict_options SET is_selected=1, chosen_duration_min=%s, "
                    "resulting_schedule_id=%s, selected_at=NOW() WHERE schedule_id=%s "
                    "AND target_task_code=%s AND option_code=%s",
                    (duration, new_id, schedule_id, target_task_code, option_code))
        insert_history(cur, user_id, new_id, week_start, new_state,
                       {**selected_option, "applied_options": applied}, "conflict_option")
    return get_schedule_view(user_id, new_id)
