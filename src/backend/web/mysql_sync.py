"""Cầu nối đồng bộ tự động từ API React Web (/api/v1/*) sang 9 bảng quan hệ chuẩn trên MySQL / TiDB Cloud.

Khi hệ thống chạy ở chế độ MySQL/TiDB Cloud (có cấu hình DB_HOST), mọi thao tác của người dùng trên
giao diện React Vite (nhập việc, xếp lịch, gỡ xung đột, lưu lịch sử, gửi form đánh giá 4 phần) đều tự
động đồng bộ sang các bảng có cấu trúc:
  user_week_settings, fixed_tasks, deadline_tasks, schedules, schedule_blocks,
  conflict_options, schedule_histories, feedbacks.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime

from backend.config import is_mysql_enabled
from backend.db import db_transaction
from backend import feedback_service
from backend.history_service import insert_history
from backend.mysql_task_repo import MySQLTaskRepository
from backend.state_codec import block_insert_rows, blocks_and_events
from conflict_resolver.models import ConflictContext, ConflictReport, PlanResult
from conflict_resolver.presentation import describe_changes
from conflict_resolver.schedule_view import build_full_schedule
from schedule_input.domain.models import ScheduleInput

logger = logging.getLogger(__name__)

_CRITERIA_KEY_MAP = {
    "coverage": "coverage",
    "priority": "priority",
    "timeliness": "deadline",
    "continuity": "continuity",
    "balance": "balance",
    "constraints": "constraints",
    "realism": "feasibility",
}

_TRADEOFF_ORDER = (
    "coverage_vs_continuity",
    "timeliness_vs_balance",
    "constraints_vs_coverage",
    "priority_vs_balance",
    "continuity_vs_timeliness",
)

_VS_MANUAL_CODE_MAP = {
    1: "much_worse",
    2: "slightly_worse",
    3: "similar",
    4: "slightly_better",
    5: "much_better",
    None: "never_self_scheduled",
}


def sync_draft(user_id: int, data: ScheduleInput, colors: dict[str, str]) -> None:
    """Đồng bộ bản nháp React sang user_week_settings, fixed_tasks, deadline_tasks."""
    if not is_mysql_enabled():
        return
    try:
        MySQLTaskRepository(user_id, data.window.week_start).save(data, colors=colors)
    except Exception:
        logger.exception("Không đồng bộ được draft sang bảng quan hệ cho user_id=%s", user_id)


def _insert_schedule_and_blocks(
    cur,
    *,
    user_id: int,
    state: dict,
    parent_id: int | None = None,
    creation_source: str = "cp_sat",
    applied_option_id: int | None = None,
) -> int:
    context = ConflictContext.model_validate(state["context"])
    result = PlanResult.model_validate(state["result"])
    week_start = date.fromisoformat(state["week_start"])

    by_id = {t.id: t for t in context.tasks}
    unscheduled = []
    for task_id, minutes in result.unscheduled.items():
        t = by_id.get(task_id)
        unscheduled.append({
            "task_code": task_id,
            "name": t.name if t else task_id,
            "missing_minutes": int(minutes),
            "mandatory": bool(t.mandatory) if t else False,
            "importance": int(t.importance) if t else 2,
        })

    cur.execute(
        "INSERT INTO schedules (user_id, parent_schedule_id, week_start, schedule_version, status, "
        "proven_optimal, creation_source, applied_option_id, total_tasks, scheduled_tasks, "
        "unscheduled_tasks, unscheduled_json, input_hash, solver_state_json) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            int(user_id), parent_id, week_start, context.schedule_version, result.status,
            1 if result.proven_optimal else 0, creation_source, applied_option_id,
            len(context.tasks), len({c.task_id for c in result.chunks}), len(unscheduled),
            json.dumps(unscheduled, ensure_ascii=False), None,
            json.dumps(state, ensure_ascii=False),
        ),
    )
    schedule_id = cur.lastrowid
    entries = build_full_schedule(context, result.chunks)
    pairs = blocks_and_events(week_start, entries, context.active_windows, state)
    rows = block_insert_rows(schedule_id, pairs, state.get("fixed_ui_ids", {}))
    if rows:
        cur.executemany(
            "INSERT INTO schedule_blocks (schedule_id, block_kind, ref_task_code, title, "
            "start_datetime, end_datetime, bg_color, text_color) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            rows,
        )
    return schedule_id


def sync_plan_created(user_id: int, state: dict) -> int | None:
    """Ghi lịch vừa xếp vào bảng schedules & schedule_blocks; trả về mysql_schedule_id."""
    if not is_mysql_enabled():
        return None
    try:
        week_start = date.fromisoformat(state["week_start"])
        context = state["context"]
        pol = context.get("policy") or {}
        with db_transaction() as cur:
            cur.execute(
                "UPDATE user_week_settings SET max_earlier_min=%s, max_later_min=%s "
                "WHERE user_id=%s AND week_start=%s",
                (int(pol.get("max_earlier_minutes", 0)), int(pol.get("max_later_minutes", 0)),
                 int(user_id), week_start),
            )
            return _insert_schedule_and_blocks(cur, user_id=user_id, state=state)
    except Exception:
        logger.exception("Không đồng bộ được lịch mới sang schedules cho user_id=%s", user_id)
        return None


def sync_conflict_analyzed(user_id: int, state: dict, target_task_code: str, report: ConflictReport) -> None:
    """Đồng bộ 3 phương án gỡ xung đột vào bảng conflict_options."""
    if not is_mysql_enabled():
        return
    schedule_id = state.get("mysql_schedule_id")
    if not schedule_id:
        return
    try:
        context = ConflictContext.model_validate(state["context"])
        week_start = date.fromisoformat(state["week_start"])
        names = {t.id: t.name for t in context.tasks}
        option_rows = []
        for option in report.options:
            changes = describe_changes(option, context, state["week_start"])
            preview = None
            if option.is_available:
                pairs = blocks_and_events(week_start, option.full_schedule, option.active_windows, state)
                preview = json.dumps([event for _, event in pairs], ensure_ascii=False)
            maximum = (option.action_payload.get("new_duration")
                       if option.option_id == 2 and option.is_available else None)
            unplaced = [{"task_code": tid, "name": names.get(tid, tid), "missing_minutes": int(m)}
                        for tid, m in option.unplaced.items()]
            option_rows.append((
                int(schedule_id), target_task_code, names.get(target_task_code, target_task_code)[:100],
                max(0, int(report.deficit_minutes)), option.option_id, option.priority_rank,
                1 if option.is_available else 0,
                (option.unavailable_reason or None) and option.unavailable_reason[:255],
                "\n".join(changes), maximum,
                json.dumps(option.action_payload, ensure_ascii=False), preview,
                json.dumps(option.warnings, ensure_ascii=False),
                json.dumps(unplaced, ensure_ascii=False),
            ))
        with db_transaction() as cur:
            cur.execute("UPDATE schedules SET solver_state_json=%s WHERE id=%s AND user_id=%s",
                        (json.dumps(state, ensure_ascii=False), int(schedule_id), int(user_id)))
            cur.executemany(
                "INSERT INTO conflict_options (schedule_id, target_task_code, target_task_name, "
                "deficit_min, option_code, priority_rank, is_available, unavailable_reason, "
                "changes_summary, max_new_duration_min, action_payload_json, preview_blocks_json, "
                "warnings_json, unplaced_json) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE target_task_name=VALUES(target_task_name), "
                "deficit_min=VALUES(deficit_min), priority_rank=VALUES(priority_rank), "
                "is_available=VALUES(is_available), unavailable_reason=VALUES(unavailable_reason), "
                "changes_summary=VALUES(changes_summary), max_new_duration_min=VALUES(max_new_duration_min), "
                "action_payload_json=VALUES(action_payload_json), "
                "preview_blocks_json=VALUES(preview_blocks_json), warnings_json=VALUES(warnings_json), "
                "unplaced_json=VALUES(unplaced_json)",
                option_rows,
            )
    except Exception:
        logger.exception("Không đồng bộ được conflict_options cho schedule_id=%s", schedule_id)


def sync_option_applied(
    user_id: int,
    prev_schedule_id: int | None,
    new_state: dict,
    target_task_code: str,
    option_code: int,
    chosen_duration: int | None,
) -> int | None:
    """Khi người dùng chọn 1 Option trên React: tạo dòng schedules mới + cập nhật conflict_options."""
    if not is_mysql_enabled():
        return None
    try:
        with db_transaction() as cur:
            new_id = _insert_schedule_and_blocks(
                cur,
                user_id=user_id,
                state=new_state,
                parent_id=prev_schedule_id,
                creation_source="conflict_option",
                applied_option_id=option_code,
            )
            if prev_schedule_id:
                cur.execute(
                    "UPDATE conflict_options SET is_selected=1, chosen_duration_min=%s, "
                    "resulting_schedule_id=%s, selected_at=NOW() "
                    "WHERE schedule_id=%s AND target_task_code=%s AND option_code=%s",
                    (chosen_duration, new_id, int(prev_schedule_id), target_task_code, int(option_code)),
                )
            return new_id
    except Exception:
        logger.exception("Không đồng bộ được option_applied cho user_id=%s", user_id)
        return prev_schedule_id


def sync_history_saved(user_id: int, state: dict, record: dict) -> None:
    """Đồng bộ bản ghi History vào bảng schedule_histories."""
    if not is_mysql_enabled():
        return
    try:
        week_start = date.fromisoformat(record["week_start"])
        week_end = date.fromisoformat(record["week_end"])
        schedule_id = state.get("mysql_schedule_id")
        with db_transaction() as cur:
            if not schedule_id:
                schedule_id = _insert_schedule_and_blocks(cur, user_id=user_id, state=state)
            applied_list = record.get("applied_options") or state.get("applied") or []
            save_source = "conflict_option" if applied_list else "manual_save"
            cur.execute(
                "INSERT IGNORE INTO schedule_histories (history_uuid, user_id, schedule_id, week_start, "
                "week_end, version, title, description, save_source, creation_method, is_complete, "
                "applied_options_json, input_snapshot_json, frozen_record_json) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    record["id"], int(user_id), int(schedule_id), week_start, week_end,
                    int(record.get("version") or 1), record.get("title") or f"Lịch {week_start}",
                    record.get("description") or "", save_source,
                    record.get("creation_method") or "cp_sat",
                    1 if record.get("complete") else 0,
                    json.dumps(applied_list, ensure_ascii=False),
                    json.dumps(state.get("input_snapshot"), ensure_ascii=False),
                    json.dumps(record, ensure_ascii=False),
                ),
            )
    except Exception:
        logger.exception("Không đồng bộ được schedule_histories cho user_id=%s", user_id)


def sync_history_deleted(user_id: int, history_uuid: str) -> None:
    if not is_mysql_enabled():
        return
    try:
        with db_transaction() as cur:
            cur.execute("DELETE FROM schedule_histories WHERE user_id=%s AND history_uuid=%s",
                        (int(user_id), history_uuid))
    except Exception:
        logger.exception("Không xóa được schedule_histories %s", history_uuid)


def sync_rating_saved(user_id: int, week_start: str, payload: dict, metrics: dict) -> None:
    """Ánh xạ dữ liệu từ RatingForm.tsx (4 phần A, B, C, D) vào bảng quan hệ feedbacks."""
    if not is_mysql_enabled():
        return
    try:
        with db_transaction() as cur:
            cur.execute(
                "SELECT id FROM schedules WHERE user_id=%s AND week_start=%s ORDER BY id DESC LIMIT 1",
                (int(user_id), week_start),
            )
            row = cur.fetchone()
            if row:
                schedule_id = row["id"]
            else:
                # Tạo bản ghi tổng hợp trong schedules nếu đánh giá từ lịch sử đã import
                cur.execute(
                    "INSERT INTO schedules (user_id, week_start, schedule_version, status, "
                    "creation_source, total_tasks, scheduled_tasks, unscheduled_tasks, solver_state_json) "
                    "VALUES (%s,%s,0,%s,%s,%s,%s,%s,'{}')",
                    (
                        int(user_id), week_start,
                        "FEASIBLE" if metrics.get("complete") else "NOT_FOUND",
                        "conflict_option" if metrics.get("options_applied") else "cp_sat",
                        int(metrics.get("tasks_total") or 0),
                        int(metrics.get("tasks_scheduled") or 0),
                        max(0, int(metrics.get("tasks_total") or 0) - int(metrics.get("tasks_scheduled") or 0)),
                    ),
                )
                schedule_id = cur.lastrowid

        criteria_mapped = {}
        for src_key, dst_key in _CRITERIA_KEY_MAP.items():
            item = (payload.get("criteria") or {}).get(src_key) or {}
            criteria_mapped[dst_key] = {
                "satisfaction": item.get("satisfaction"),
                "importance": item.get("importance"),
            }

        raw_tradeoffs = payload.get("tradeoffs") or {}
        # RatingForm dùng thang -2..+2 -> đổi sang thang 1..5 của bảng feedbacks (cộng 3)
        tradeoffs_mapped = [int(raw_tradeoffs[k]) + 3 for k in _TRADEOFF_ORDER]

        problems = list(payload.get("problems") or [])
        if not problems:
            problems = ["no_significant_issues"]

        mapped_payload = {
            "criteria": criteria_mapped,
            "tradeoffs": tradeoffs_mapped,
            "overall_satisfaction": payload["overall"],
            "usage_intent": payload["adoption"],
            "vs_self_scheduling": _VS_MANUAL_CODE_MAP.get(payload.get("vs_manual"), "never_self_scheduled"),
            "nps_score": payload["nps"],
            "conflict_clarity_score": payload.get("conflict_clarity"),
            "reported_issues": problems,
            "best_aspect": payload.get("comment_good") or "",
            "needs_improvement": payload.get("comment_improve") or "",
            "system_metrics": metrics,
        }
        feedback_service.submit_feedback(int(user_id), int(schedule_id), mapped_payload)
    except Exception:
        logger.exception("Không đồng bộ được đánh giá sang bảng feedbacks cho user_id=%s", user_id)
