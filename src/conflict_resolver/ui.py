import asyncio
import json
from datetime import date, datetime, timedelta, timezone

import streamlit as st
from scheduling_algorithm.core_algorithm.history import (
    DEFAULT_HISTORY_PATH, delete_schedule_history, load_schedule_history, save_selected_schedule,
)
from .calendar_view import (
    PREVIEW_CSS, calendar_events, deadline_styles as build_deadline_styles,
    option_preview_html, schedule_blocks,
)
from .presentation import describe_changes
from .errors import SolverInconclusive
from .ai.advisor import get_settings
from .models import Interval, Policy, ScheduleEntry
from .planning import (
    PlanningSession,
    context_from_snapshot,
)


def _history_path():
    """Mỗi người dùng đăng nhập có file lịch sử riêng; không đăng nhập thì dùng file chung cũ."""
    return st.session_state.get("history_path", DEFAULT_HISTORY_PATH)


def _history_schedule_data(record, lang):
    """Rebuild display data from a snapshot, without changing the live session."""
    week_start = date.fromisoformat(record["week_start"])
    context, result = record["context"], record["result"]
    tasks = context.get("tasks", [])
    names = {task["id"]: task["name"] for task in tasks}
    entries = [
        ScheduleEntry(kind="TASK", ref_id=chunk["task_id"],
                      name=names.get(chunk["task_id"], chunk["task_id"]),
                      start=chunk["start"], end=chunk["end"],
                      buffer_end=chunk.get("buffer_end", chunk["end"]))
        for chunk in result.get("chunks", [])
    ]
    entries.extend(
        ScheduleEntry(kind="FIXED", ref_id=fixed["id"], name=fixed["name"],
                      start=fixed["interval"]["start"], end=fixed["interval"]["end"],
                      ancillary=fixed.get("ancillary", False))
        for fixed in context.get("fixed_tasks", [])
    )
    entries.sort(key=lambda entry: (entry.start, entry.end, entry.ref_id))
    windows = [Interval(**window) for window in context.get("active_windows", [])]
    styles = build_deadline_styles([
        {"id": task["id"], "importance": task.get("importance", 2)} for task in tasks
    ])
    blocks = schedule_blocks(entries, windows, lang)
    return week_start, entries, blocks, styles


def _edit_history_schedule(record):
    """Load an independent editable draft; never update the history record."""
    from scheduling_algorithm.core_algorithm.history_input import input_from_history

    service = st.session_state.get("service")
    if service is None:
        raise ValueError("Chưa mở trang nhập dữ liệu.")
    candidate, notes = input_from_history(record)
    service.repository.save(candidate, candidate.window.now)
    service.history.append(service.data)
    service.data = candidate
    service.now_override = candidate.window.now
    for key in list(st.session_state):
        if (key in {"snapshot", "planning", "planning_snapshot", "planning_applied_options",
                    "edit_request", "planned_click", "schedule_history_notice", "calendar_error",
                    "calendar_message", "ask_clear", "ask_sample", "rating_open_key", "rating_submitted_key"}
                or key.startswith(("table_error_", "table_event_", "form_"))):
            st.session_state.pop(key, None)
    st.session_state.page = "input"
    st.session_state.old_week = False
    st.session_state.preview_current_week = False
    st.session_state.calendar_fullscreen = False
    st.session_state.rev = st.session_state.get("rev", 0) + 1
    st.session_state.notes = ["Đã nạp bản sao của lịch đã lưu để chỉnh sửa. Lịch sử gốc được giữ nguyên.", *notes]


def render_history(lang="vi"):
    """Browse all saved weeks independently of the current planning result."""
    if st.session_state.pop("history_reset_filters", False):
        st.session_state.pop("schedule_history_week", None)
        st.session_state.pop("schedule_history_version", None)
    notice = st.session_state.pop("history_delete_notice", None)
    if notice:
        st.success(notice)
    try:
        records = load_schedule_history(_history_path())
    except (OSError, ValueError) as exc:
        st.error("Không đọc được lịch sử: " + str(exc))
        return
    if not records:
        st.info("Chưa có lịch được lưu. Bấm Lưu lịch hiện tại vào history để tạo phiên bản đầu tiên.")
        return

    try:
        weeks = sorted({record["week_start"] for record in records}, reverse=True)
        for week in weeks:
            date.fromisoformat(week)
        by_id = {record["id"]: record for record in records}
    except (KeyError, TypeError, ValueError) as exc:
        st.error("Thông tin phiên bản trong history không hợp lệ: " + str(exc))
        return

    def week_label(value):
        if value is None:
            return "Tất cả các tuần"
        start = date.fromisoformat(value)
        return f"{start:%d/%m/%Y} – {start + timedelta(days=6):%d/%m/%Y}"

    selected_week = st.selectbox("Tuần của lịch", options=[None] + weeks,
                                 format_func=week_label, key="schedule_history_week")
    choices = [record["id"] for record in records
               if selected_week is None or record["week_start"] == selected_week]

    def record_label(record_id):
        record = by_id[record_id]
        title = record.get("title") or (
            f"Lịch {week_label(record['week_start'])} · Phiên bản {record.get('version', 'cũ')}"
        )
        return title + " · " + record.get("saved_at_display", record.get("saved_at", ""))

    record_id = st.selectbox("Chọn phiên bản đã lưu", options=choices,
                             format_func=record_label, key="schedule_history_version")
    record = by_id[record_id]
    if st.session_state.get("history_delete_record") not in (None, record_id):
        st.session_state.pop("history_delete_record", None)
    view, edit, delete = st.columns(3)
    if view.button("Xem lịch", key=f"history_view_{record_id}"):
        st.session_state.history_view_record = record_id
    if edit.button("Chỉnh sửa lịch", key=f"history_edit_{record_id}"):
        try:
            _edit_history_schedule(record)
        except (KeyError, OSError, TypeError, ValueError) as exc:
            st.error("Không nạp được lịch để chỉnh sửa: " + str(exc))
            return
        st.rerun()
    if delete.button("Xóa lịch", key=f"history_delete_{record_id}"):
        st.session_state.history_delete_record = record_id
    if st.session_state.get("history_delete_record") == record_id:
        st.warning("Xóa phiên bản này khỏi lịch sử? " + record_label(record_id))
        confirm, cancel = st.columns(2)
        if confirm.button("Xác nhận xóa", key=f"history_delete_confirm_{record_id}"):
            try:
                delete_schedule_history(record_id, path=_history_path())
            except (OSError, ValueError, TypeError) as exc:
                st.error("Chưa xóa được lịch: " + str(exc))
                return
            st.session_state.pop("history_delete_record", None)
            if st.session_state.get("history_view_record") == record_id:
                st.session_state.pop("history_view_record", None)
            # Reset widget selections on the next render, before creating them.
            st.session_state.history_reset_filters = True
            st.session_state.history_delete_notice = "Đã xóa phiên bản lịch khỏi history."
            st.rerun()
        if cancel.button("Hủy", key=f"history_delete_cancel_{record_id}"):
            st.session_state.pop("history_delete_record", None)
            st.rerun()
    if st.session_state.get("history_view_record") != record_id:
        return
    try:
        week_start, entries, blocks, styles = _history_schedule_data(record, lang)
    except (KeyError, TypeError, ValueError) as exc:
        st.error("Không dựng được lịch từ phiên bản này: " + str(exc))
        return

    st.write(record.get("title") or record_label(record_id))
    saved_display = record.get("saved_at_display")
    if not saved_display and record.get("saved_at"):
        try:
            saved_display = datetime.fromisoformat(record["saved_at"]).astimezone(
                timezone(timedelta(hours=7))
            ).strftime("%d/%m/%Y %H:%M:%S")
        except ValueError:
            saved_display = record["saved_at"]
    if saved_display:
        st.caption("Đã lưu lúc " + saved_display + " · giờ Việt Nam")
    if record.get("description"):
        st.write(record["description"])

    remaining = record["result"].get("unscheduled") or {}
    if remaining:
        names = {task["id"]: task["name"] for task in record["context"].get("tasks", [])}
        st.warning("Phiên bản này còn task chưa xếp: " + ", ".join(
            f"{names.get(task_id, task_id)} ({minutes} phút)" for task_id, minutes in remaining.items()
        ))
    else:
        st.success("Phiên bản này đã xếp đầy đủ các task còn giữ.")

    from streamlit_calendar import calendar

    calendar(
        events=calendar_events(week_start, blocks, styles, {}),
        options={
            "initialView": "timeGridWeek", "initialDate": week_start.isoformat(),
            "firstDay": 1, "locale": "vi" if lang == "vi" else "en-gb",
            "headerToolbar": False, "allDaySlot": False, "height": 580,
            "editable": False, "eventDurationEditable": False,
            "slotMinTime": "00:00:00", "slotMaxTime": "24:00:00", "scrollTime": "06:00:00",
            "displayEventEnd": True,
            "eventTimeFormat": {"hour": "2-digit", "minute": "2-digit", "hour12": False},
            "slotLabelFormat": {"hour": "2-digit", "minute": "2-digit", "hour12": False},
        },
        key=f"saved_schedule_calendar_{record_id}_{lang}",
    )
    if st.checkbox("Xem bảng chi tiết theo thời gian", key="schedule_history_table"):
        origin = datetime.combine(week_start, datetime.min.time())
        rows = [{
            "Công việc": entry.name,
            "Loại": "Task" if entry.kind == "TASK" else "Chuẩn bị / đi về" if entry.ancillary else "Fixed task",
            "Bắt đầu": (origin + timedelta(minutes=entry.start)).strftime("%d/%m/%Y %H:%M"),
            "Kết thúc": (origin + timedelta(minutes=entry.end)).strftime("%d/%m/%Y %H:%M"),
        } for entry in entries]
        st.dataframe(rows, hide_index=True, use_container_width=True)
    st.download_button("Tải phiên bản lịch này (JSON)",
                       data=json.dumps(record, ensure_ascii=False, indent=2),
                       file_name=f"schedule_{record['week_start']}_v{record.get('version', 'old')}.json",
                       mime="application/json", key="download_schedule_history")


def render(snapshot, controls, fixed_colors, deadline_styles, lang="vi"):
    token = snapshot.to_json()
    week_start = date.fromisoformat(snapshot.to_dict()["window"]["week_start"])

    with controls:
        with st.expander("Xem lịch sử lịch đã lưu"):
            render_history(lang)
        st.subheader("Xếp lịch và xử lý conflict")
        morning, evening = st.columns(2)
        earlier = morning.number_input(
            "Cho phép thức dậy sớm hơn (phút)", min_value=0, max_value=60, value=0
        )
        later = evening.number_input(
            "Cho phép ngủ muộn hơn (phút)", min_value=0, max_value=60, value=0
        )
        if st.button("Chạy thuật toán xếp lịch", type="primary"):
            try:
                policy = Policy(max_earlier_minutes=earlier, max_later_minutes=later)
                st.session_state.planning = PlanningSession(context_from_snapshot(snapshot, policy))
                st.session_state.planning_snapshot = token
                st.session_state.planning_applied_options = []
            except ValueError as exc:
                st.error(str(exc))

    session = st.session_state.get("planning")

    if session is None or st.session_state.get("planning_snapshot") != token:
        return

    history_notice = st.session_state.pop("schedule_history_notice", None)
    if history_notice:
        level, message = history_notice
        if level == "success":
            st.success(message)
        else:
            st.error(message)

    try:
        result = session.plan()
    except SolverInconclusive as exc:
        st.warning(str(exc))
        if st.button("Thử lại"):
            st.rerun()
        return
    if result.proven_optimal:
        st.caption("Lịch đã được chứng minh tối ưu.")
    else:
        st.caption(
            "Đây là lịch tốt nhất tìm được trong thời gian giới hạn. "
            "Có thể vẫn còn cách xếp giữ lại được nhiều task hơn."
        )
    names = {
        task.id: task.name
        for task in session.context.tasks
    }

    if result.unscheduled:
        target_id = st.selectbox(
            "Task chưa xếp được",
            options=list(result.unscheduled),
            format_func=lambda task_id: names[task_id],
        )

        if st.button("Phân tích 3 lựa chọn"):
            with st.spinner("Đang kiểm chứng phương án..."):
                try:
                    asyncio.run(session.analyze(target_id, get_settings()))
                except ValueError as exc:
                    st.error(str(exc))

        if target_id in session.reports:
            report, _ = session.reports[target_id]
            st.caption(f"Trạng thái AI: {report.ai_status}")
            st.html(PREVIEW_CSS)
            titles = {
                1: "Bỏ task khỏi tuần",
                2: "Giảm thời lượng task",
                3: "Nới ràng buộc",
            }

            for option in report.options:
                heading = f"Lựa chọn {option.option_id} · {titles[option.option_id]}"

                if option.is_available:
                    preview = schedule_blocks(option.full_schedule, option.active_windows, lang)
                    st.html(option_preview_html(heading, week_start, preview, deadline_styles, fixed_colors, lang))
                    st.markdown(
                        "**Phương án đề xuất đã được kiểm chứng:**"
                    )
                else:
                    st.subheader(heading)
                    st.markdown("**Tình trạng phương án:**")

                descriptions = describe_changes(
                    option,
                    session.context,
                    week_start.isoformat(),
                )

                for description in descriptions:
                    st.write("• " + description)

                if report.ai_status == "SUCCESS":
                    st.markdown(
                        "**AI giải thích và đánh giá:**"
                    )
                    st.write(option.ai_description)
                else:
                    st.caption(
                        "Chưa có nhận xét AI hợp lệ; "
                        "đang hiển thị mô tả từ engine."
                    )

                for warning in option.warnings:
                    st.caption(warning)
                if option.is_available and option.unplaced:
                    st.caption("Vẫn chưa xếp được: " + ", ".join(
                        f"{names.get(task_id, task_id)} ({minutes} phút)"
                        for task_id, minutes in option.unplaced.items()
                    ))
                duration = None

                if (
                    option.option_id == 2
                    and option.is_available
                ):
                    task = next(
                        task
                        for task in session.context.tasks
                        if task.id == target_id
                    )

                    maximum = option.action_payload[
                        "new_duration"
                    ]

                    duration = st.number_input(
                        "Thời lượng mới (phút)",
                        min_value=task.min_remaining_min,
                        max_value=maximum,
                        value=maximum,
                        key=f"duration_{target_id}",
                    )
                    if duration != maximum:
                        st.caption(f"Lịch xem thử dùng mức đã kiểm chứng là {maximum} phút. "
                                   "Mức bạn nhập sẽ được kiểm chứng khi áp dụng.")

                if st.button(
                    f"Áp dụng option {option.option_id}",
                    disabled=not option.is_available,
                ):
                    try:
                        selected_result = session.apply(
                            target_id,
                            option.option_id,
                            report.schedule_version,
                            duration,
                        )

                        chosen_action = dict(option.action_payload)
                        if option.option_id == 2 and duration is not None:
                            chosen_action["new_duration"] = duration

                        selected_option = {
                            "source": "conflict_option",
                            "target_task_id": target_id,
                            "target_task_name": names.get(target_id, target_id),
                            "option_id": option.option_id,
                            "duration_min": duration,
                            "action_payload": chosen_action,
                            "schedule_version": session.context.schedule_version,
                        }
                        applied_options = list(st.session_state.get("planning_applied_options", []))
                        applied_options.append(selected_option)
                        st.session_state.planning_applied_options = applied_options

                        st.session_state.schedule_history_notice = (
                            "success",
                            "Đã áp dụng phương án; chưa lưu vào history.",
                        )

                        st.rerun()

                    except (ValueError, SolverInconclusive) as exc:
                        st.error(str(exc))

    else:
        st.success(
            "Đã xếp đầy đủ các task còn giữ."
        )

    if st.button("Lưu lịch hiện tại vào history"):
        try:
            save_selected_schedule(
                context=session.context,
                result=result,
                week_start=week_start.isoformat(),
                selection={
                    "source": "manual_save",
                    "applied_options": st.session_state.get("planning_applied_options", []),
                },
                path=_history_path(),
                input_snapshot=snapshot.to_dict(),
            )
        except (OSError, ValueError, TypeError) as exc:
            st.error("Chưa lưu được history: " + str(exc))
        else:
            st.session_state.schedule_history_notice = (
                "success", "Đã lưu lịch hiện tại vào history.",
            )
            st.rerun()

    export_data = {
        "context": session.context.model_dump(),
        "result": result.model_dump(),
    }

    user = st.session_state.get("auth_user")
    applied = list(st.session_state.get("planning_applied_options", []))
    download_args = {}
    if user is not None:
        from user_portal.ui_rating import finalize_schedule

        # Tải lịch xuống cũng được xem là đã chốt lịch: bảng đánh giá sẽ tự mở.
        download_args = {"on_click": finalize_schedule,
                         "args": (user, export_data["context"], export_data["result"],
                                  week_start.isoformat(), applied)}

    st.download_button(
        "Lưu lịch và trạng thái JSON",
        data=json.dumps(
            export_data,
            ensure_ascii=False,
            indent=2,
        ),
        file_name="schedule.json",
        mime="application/json",
        **download_args,
    )
    if user is not None:
        from user_portal.ui_rating import render_finalize_and_rating

        render_finalize_and_rating(user, export_data["context"], export_data["result"],
                                   week_start.isoformat(), applied)
    return session.context, result
