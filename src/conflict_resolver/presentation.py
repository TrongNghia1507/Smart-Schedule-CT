from datetime import datetime, timedelta


def describe_changes(option, context, week_start):
    def moment(minute):
        value = (
            datetime.fromisoformat(week_start)
            + timedelta(minutes=minute)
        )
        return value.strftime("%d/%m/%Y %H:%M")

    tasks = {
        task.id: task
        for task in context.tasks
    }

    fixed_tasks = {
        task.id: task
        for task in context.fixed_tasks
    }

    payload = option.action_payload

    task = tasks.get(payload.get("task_id"))

    name = (
        task.name
        if task is not None
        else "công việc đang chọn"
    )

    if not option.is_available:
        return [
            option.unavailable_reason
            or "Chưa tìm được phương án hợp lệ."
        ]

    if option.option_id == 1:
        lines = [
            (
                f"Bỏ “{name}” khỏi kế hoạch tuần; "
                "chưa đánh dấu hoàn thành."
            )
        ]

        if payload.get("was_mandatory"):
            lines.append(
                "Đây là task bắt buộc; chỉ bỏ khi bạn "
                "chủ động chọn phương án này."
            )

        return lines

    if option.option_id == 2:
        old_duration = payload["old_duration"]
        new_duration = payload["new_duration"]

        lines = [
            (
                f"Đề xuất giảm “{name}” từ "
                f"{old_duration} xuống {new_duration} phút, "
                f"giảm {old_duration - new_duration} phút."
            ),
            (
                "Giữ nguyên deadline; "
                "chỉ thay đổi thời lượng công việc."
            ),
        ]

        if payload.get("maximum_proven"):
            lines.append(
                "Engine đã chứng minh đây là thời lượng "
                "lớn nhất có thể giữ lại trong phạm vi kiểm tra."
            )
        else:
            lines.append(
                "Đây là thời lượng khả thi tìm được; "
                "chưa chứng minh là mức lớn nhất."
            )

        return lines

    

    lines = []

    days = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ nhật"]

    def clock(minute):
        value = minute % 1440
        return f"{value // 60:02}:{value % 60:02}"

    def day_name(minute):
        return days[min(minute // 1440, 6)]

    changes = payload.get("changes", [])

    for change in changes:
        if change["operation"] != "REMOVE_FIXED":
            continue

        lines.append(
            f"Xóa “{change['name']}” {day_name(change['start'])} "
            f"{moment(change['start'])[:10]} "
            f"({clock(change['start'])}–{clock(change['end'])}); "
            f"giải phóng {change['removed_minutes']} phút."
        )

    for change in changes:
        if change["operation"] != "EXPAND_ACTIVE_WINDOW":
            continue

        window = context.active_windows[change["window_index"]]
        day = day_name(window.start)

        earlier = change.get(
            "earlier_minutes", window.start - change["new_start"]
        )
        later = change.get(
            "later_minutes", change["new_end"] - window.end
        )

        if earlier:
            lines.append(
                f"{day}: dậy sớm hơn {earlier} phút "
                f"({clock(window.start)} → {clock(change['new_start'])})."
            )

        if later:
            lines.append(
                f"{day}: thức muộn hơn {later} phút "
                f"({clock(window.end)} → {clock(change['new_end'])})."
            )

    lines.append(
        "Giữ nguyên thời lượng và deadline "
        "của task đang xử lý."
    )

    return lines
