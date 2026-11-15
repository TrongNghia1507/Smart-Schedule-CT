"""Khối giao diện Streamlit: hiển thị kết quả kiểm tra thời gian và các phương án của resolver."""
import streamlit as st

from schedule_input.ui.i18n import EN, tr

from .edits import apply_edits, is_auto_applicable, option_to_edits
from .model import describe_minute
from .service import check_feasibility_sync

EN.update({
    "Kiểm tra thời gian": "Time feasibility check",
    "Đủ thời gian cho các việc có deadline.": "There is enough time for all deadline tasks.",
    "Chi tiết từng mốc hạn chót": "Details per deadline",
    "Phương án xử lý": "Ways to resolve",
    "Áp dụng": "Apply",
    "Không khả dụng": "Not available",
    "Cần chỉnh thủ công; không tự áp dụng được.": "Needs manual changes; cannot be applied automatically.",
    "Bỏ qua cảnh báo, vẫn tiếp tục": "Ignore the warning and continue",
    "Các mốc thiếu khác sẽ được xử lý sau khi xong mốc này:": "Other short deadlines are handled after this one:",
    "Không gọi được bộ xử lý xung đột: ": "Could not reach the conflict resolver: ",
    "Gỡ việc khỏi tuần": "Drop the task from this week",
    "Rút gọn thời lượng": "Shorten the task",
    "Dời hạn chót": "Move a deadline",
    "Nới ràng buộc (rút việc cố định / mượn giờ ngủ)": "Relax constraints (shorten fixed tasks / borrow sleep)",
})

LABELS = {
    1: "Gỡ việc khỏi tuần",
    2: "Rút gọn thời lượng",
    3: "Dời hạn chót",
    4: "Nới ràng buộc (rút việc cố định / mượn giờ ngủ)",
}


def _fingerprint(data):
    now = data.window.now.replace(second=0, microsecond=0)
    return repr((
        data.window.week_start, data.window.sleep, now,
        sorted(repr(task) for task in data._tasks.values()),
    ))


def _report_for(service):
    key = _fingerprint(service.data)
    cached = st.session_state.get("feasibility_cache")
    if not cached or cached[0] != key:
        report = check_feasibility_sync(
            service.data, schedule_version=st.session_state.get("rev", 0)
        )
        st.session_state["feasibility_cache"] = (key, report)
        return report
    return cached[1]


def render_feasibility(service, on_applied):
    """Vẽ khối kiểm tra; trả về True nếu đang chặn bước xác nhận."""
    report = _report_for(service)

    with st.container(border=True, key="feasibility_card"):
        st.subheader(tr("Kiểm tra thời gian"))

        if report.status == "NOT_CHECKED":
            for note in report.notes:
                st.info(tr(note))
            return False

        if report.status == "OK":
            st.success(tr("Đủ thời gian cho các việc có deadline."))
            for note in report.notes:
                st.caption(tr(note))
            if report.checkpoints:
                with st.expander(tr("Chi tiết từng mốc hạn chót")):
                    for cp in report.checkpoints:
                        st.caption(
                            f"{describe_minute(cp.deadline)} — cần {cp.demand} / trống {cp.free} phút"
                        )
            return False

        # --- CONFLICT -------------------------------------------------------
        resolved = report.resolved
        for finding in report.findings:
            if finding is resolved:
                st.error(tr(finding.message))
        others = [f for f in report.findings if f is not resolved]
        if others:
            st.caption(tr("Các mốc thiếu khác sẽ được xử lý sau khi xong mốc này:"))
            for finding in others:
                st.caption("• " + tr(finding.message))

        if report.resolver_error:
            st.warning(tr("Không gọi được bộ xử lý xung đột: ") + report.resolver_error)
        elif report.resolution:
            st.markdown("**" + tr("Phương án xử lý") + "**")
            for option in sorted(report.resolution.options, key=lambda o: o.priority_rank):
                label = tr(LABELS[option.option_id])
                with st.container(border=True):
                    if not option.is_available:
                        st.markdown(f"~~{label}~~ — {tr('Không khả dụng')}")
                        st.caption(option.unavailable_reason or "")
                        continue

                    edits = option_to_edits(option, report.model, service.data)
                    st.markdown(f"**{label}**")
                    for edit in edits:
                        st.write("• " + edit.description)
                    if option.ai_description and option.ai_description != option.factual_description:
                        st.caption(option.ai_description)
                    for warning in option.warnings:
                        st.caption("⚠ " + warning)

                    if not is_auto_applicable(edits):
                        st.caption(tr("Cần chỉnh thủ công; không tự áp dụng được."))
                    elif st.button(
                        tr("Áp dụng"),
                        key=f"feasibility_apply_{resolved.deadline}_{option.option_id}",
                    ):
                        result = apply_edits(service, edits)
                        if result.has_errors():
                            for issue in result.issues:
                                st.error(tr(issue.message))
                        else:
                            st.session_state.pop("feasibility_cache", None)
                            on_applied()

        ignore = st.checkbox(tr("Bỏ qua cảnh báo, vẫn tiếp tục"), key="feasibility_ignore")
        return not ignore
