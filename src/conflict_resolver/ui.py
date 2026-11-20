import asyncio
import json
from datetime import date

import streamlit as st
from .calendar_view import PREVIEW_CSS, option_preview_html, schedule_blocks
from .presentation import describe_changes
from .errors import SolverInconclusive
from .ai.advisor import get_settings
from .models import Policy
from .planning import (
    PlanningSession,
    context_from_snapshot,
)


def render(snapshot, controls, fixed_colors, deadline_styles, lang="vi"):
    token = snapshot.to_json()
    week_start = date.fromisoformat(snapshot.to_dict()["window"]["week_start"])

    with controls:
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
            except ValueError as exc:
                st.error(str(exc))

    session = st.session_state.get("planning")

    if session is None or st.session_state.get("planning_snapshot") != token:
        return

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
                        session.apply(
                            target_id,
                            option.option_id,
                            report.schedule_version,
                            duration,
                        )

                        st.rerun()

                    except ValueError as exc:
                        st.error(str(exc))

    else:
        st.success(
            "Đã xếp đầy đủ các task còn giữ."
        )

    export_data = {
        "context": session.context.model_dump(),
        "result": result.model_dump(),
    }

    st.download_button(
        "Lưu lịch và trạng thái JSON",
        data=json.dumps(
            export_data,
            ensure_ascii=False,
            indent=2,
        ),
        file_name="schedule.json",
        mime="application/json",
    )
    return session.context, result
