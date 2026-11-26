"""Đóng gói / khôi phục PlanningSession <-> JSON (cột schedules.solver_state_json) và dựng khối lịch.

Server không giữ trạng thái trong RAM: mọi thứ cần để phân tích / áp dụng conflict nằm trong state.
"""
from __future__ import annotations

from datetime import date, datetime

from conflict_resolver.calendar_view import calendar_events, deadline_styles, schedule_blocks
from conflict_resolver.models import Chunk, ConflictContext, ConflictReport, FixedTask, Interval, PlanResult, Policy
from conflict_resolver.planning import PlanningSession

DYNAMIC_KEYS = ("context", "result", "protected_ids", "hint_chunks", "reports")


def dump_state(session: PlanningSession, result: PlanResult, base: dict) -> dict:
    return {
        **base,
        "context": session.context.model_dump(mode="json"),
        "result": result.model_dump(mode="json"),
        "protected_ids": sorted(session.protected_ids),
        "hint_chunks": [c.model_dump(mode="json") for c in session.hint_chunks],
        "reports": {tid: {"report": report.model_dump(mode="json"),
                          "scoped": scoped.model_dump(mode="json")}
                    for tid, (report, scoped) in session.reports.items()},
    }


def base_of(state: dict) -> dict:
    """Phần bất biến / tích lũy của state (không gồm các khóa do session sinh ra)."""
    return {k: v for k, v in state.items() if k not in DYNAMIC_KEYS}


def load_planning_session(state: dict) -> PlanningSession:
    context = state["context"]
    if context["tasks"]:
        loaded_context = ConflictContext.model_validate(context)
    else:
        # Applying "exclude" to the last remaining task can produce a valid
        # result with no deadline tasks. The public input model requires one.
        loaded_context = ConflictContext.model_construct(**{
            **context,
            "fixed_tasks": [FixedTask.model_validate(item) for item in context["fixed_tasks"]],
            "active_windows": [Interval.model_validate(item) for item in context["active_windows"]],
            "policy": Policy.model_validate(context["policy"]),
        })
    session = PlanningSession(
        context=loaded_context,
        protected_ids=set(state.get("protected_ids", [])),
        cached_plan=PlanResult.model_validate(state["result"]),  # không giải lại baseline
        hint_chunks=[Chunk.model_validate(c) for c in state.get("hint_chunks", [])],
    )
    session.reports = {
        tid: (ConflictReport.model_validate(v["report"]), ConflictContext.model_validate(v["scoped"]))
        for tid, v in state.get("reports", {}).items()
    }
    return session


def ui_code(ref_id: str | None, fixed_ui_ids: dict) -> str | None:
    """id engine ('F2@1.prep') -> task_code ('ft_...'); id deadline giữ nguyên; khối ngủ -> None."""
    if not ref_id:
        return None
    prefix = ref_id.split("@")[0].split(".")[0]
    return fixed_ui_ids.get(prefix, ref_id)


def blocks_and_events(week_start: date, entries, active_windows, state: dict) -> list:
    """Danh sách (Block, event FullCalendar) của một bảng lịch."""
    blocks = schedule_blocks(entries, active_windows, state.get("lang", "vi"))
    styles = deadline_styles(state["deadline_order"])
    events = calendar_events(week_start, blocks, styles, state.get("fixed_colors", {}))
    return list(zip(blocks, events))


def block_insert_rows(schedule_id: int, pairs: list, fixed_ui_ids: dict) -> list[tuple]:
    rows = []
    for block, event in pairs:
        rows.append((schedule_id, block.kind, ui_code(block.ref_id, fixed_ui_ids),
                     block.title[:200] if block.title else "",
                     datetime.fromisoformat(event["start"]), datetime.fromisoformat(event["end"]),
                     event["backgroundColor"], event["textColor"]))
    return rows


def block_row_to_event(row: dict) -> dict:
    kind = row["block_kind"]
    start, end = row["start_datetime"], row["end_datetime"]
    classes = [f"{kind}-band"]
    if kind == "deadline" and (end - start).total_seconds() < 30 * 60:
        classes.append("short-event")
    event = {
        "id": f"blk-{row['id']}", "title": row["title"],
        "start": start.isoformat(), "end": end.isoformat(),
        "backgroundColor": row["bg_color"], "borderColor": row["bg_color"],
        "textColor": row["text_color"], "editable": False, "classNames": classes,
        "extendedProps": {"kind": kind, "task_code": row["ref_task_code"]},
    }
    if kind == "sleep":
        event["display"] = "background"
    else:
        event["interactive"] = True
    return event
