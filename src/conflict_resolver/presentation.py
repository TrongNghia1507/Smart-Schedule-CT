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
        return [
            (
                f"Bỏ “{name}” khỏi kế hoạch tuần; "
                "chưa đánh dấu hoàn thành."
            )
        ]

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

    for change in payload.get("changes", []):
        if change["operation"] == "SHORTEN_FIXED":
            fixed = fixed_tasks[change["task_id"]]

            old_duration = (
                change["old_end"]
                - fixed.interval.start
            )

            new_duration = (
                change["new_end"]
                - fixed.interval.start
            )

            occurrence_date = moment(
                fixed.interval.start
            )[:10]

            old_end = moment(change["old_end"])
            new_end = moment(change["new_end"])

            lines.append(
                f"Rút “{fixed.name}” ngày {occurrence_date} "
                f"từ {old_duration} xuống {new_duration} phút; "
                f"giờ kết thúc đổi từ {old_end} "
                f"thành {new_end}."
            )

        elif change["operation"] == "EXPAND_ACTIVE_WINDOW":
            window = context.active_windows[
                change["window_index"]
            ]

            old_start = moment(window.start)
            old_end = moment(window.end)

            new_start = moment(change["new_start"])
            new_end = moment(change["new_end"])

            lines.append(
                "Đổi khung giờ thức từ "
                f"{old_start} – {old_end} thành "
                f"{new_start} – {new_end}."
            )

    lines.append(
        "Giữ nguyên thời lượng và deadline "
        "của task đang xử lý."
    )

    return lines