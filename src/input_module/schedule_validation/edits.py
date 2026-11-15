"""Chuyển action_payload của Option (ngôn ngữ resolver) thành thay đổi trên dữ liệu input."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field

from schedule_input.application.mapper import TaskFactory, hh
from schedule_input.domain.models import FixedTask, Severity
from schedule_input.domain.validation import ValidationReport, ValidationService

from .model import describe_minute


@dataclass(frozen=True)
class InputEdit:
    op: str                       # SET_FIELDS | REMOVE_TASK | MANUAL
    task_id: str | None
    fields: dict = field(default_factory=dict)
    description: str = ""

    @property
    def auto(self):
        return self.op != "MANUAL"


def option_to_edits(option, model, data):
    """Danh sách InputEdit; option chỉ tự áp dụng được nếu mọi edit đều auto."""
    payload = option.action_payload or {}
    operation = payload.get("operation")

    if operation == "COMPRESS_TASK":
        return [InputEdit(
            "SET_FIELDS", payload["task_id"],
            {"remaining_min": str(payload["new_duration"])},
            f"Giảm thời lượng còn {payload['new_duration']} phút.",
        )]

    if operation == "POSTPONE_TASK":
        deadline = model.to_datetime(payload["new_deadline"])
        return [InputEdit(
            "SET_FIELDS", payload["task_id"],
            {"deadline": deadline.isoformat(timespec="minutes")},
            f"Dời hạn chót đến {describe_minute(payload['new_deadline'])}.",
        )]

    if operation == "EXCLUDE_FROM_WEEK":
        return [InputEdit(
            "REMOVE_TASK", payload["task_id"],
            description="Gỡ việc khỏi danh sách (có thể Hoàn tác).",
        )]

    edits, seen = [], set()
    for change in payload.get("changes", []):
        kind = change.get("operation")

        if kind == "SHORTEN_FIXED":
            occ = model.occurrence(change["task_id"])
            task = data._tasks.get(occ.task_id) if occ else None
            if not isinstance(task, FixedTask):
                edits.append(InputEdit("MANUAL", None, description="Rút ngắn một việc cố định."))
                continue
            if task.id in seen:
                continue
            seen.add(task.id)

            minutes = task.flexibility.min_min
            end = task.time_range.start + minutes
            end = end - 1440 if end > 1440 else end
            note = " (áp dụng cho cả chuỗi lặp)" if not task.repeat.is_one_off() else ""
            edits.append(InputEdit(
                "SET_FIELDS", task.id, {"end": hh(end)},
                f"Rút ngắn “{task.name}” còn {minutes} phút{note}.",
            ))

        elif kind == "EXPAND_ACTIVE_WINDOW":
            window = model.windows[change["window_index"]]
            parts = []
            if change["new_start"] < window.start:
                parts.append(
                    f"thức dậy sớm hơn {window.start - change['new_start']} phút "
                    f"(từ {describe_minute(change['new_start'])})"
                )
            if change["new_end"] > window.end:
                parts.append(
                    f"đi ngủ muộn hơn {change['new_end'] - window.end} phút "
                    f"(đến {describe_minute(change['new_end'])})"
                )
            edits.append(InputEdit(
                "MANUAL", None,
                description="Điều chỉnh giờ ngủ thủ công: " + " và ".join(parts) + ".",
            ))

    return edits


def is_auto_applicable(edits):
    return bool(edits) and all(e.auto for e in edits)


def apply_edits(service, edits):
    """Áp dụng nguyên tử qua cùng đường validate/lưu/undo của TaskInputService."""
    report = ValidationReport()
    if not is_auto_applicable(edits):
        report.add("X01", Severity.ERROR, "", "", "Phương án này cần chỉnh thủ công.")
        return report

    candidate = deepcopy(service.data)

    for edit in edits:
        if edit.op == "REMOVE_TASK":
            candidate.remove(edit.task_id)
            continue

        old = candidate.get_by_id(edit.task_id)
        fixed = isinstance(old, FixedTask)
        raw = TaskFactory.to_row_view(old)
        raw.update(edit.fields)
        task, result = TaskFactory.from_raw(raw, fixed)
        report.issues.extend(result.issues)
        if task:
            candidate.update(task)

    if report.has_errors():
        return report

    full = ValidationService().validate_all(candidate)
    report.issues.extend(i for i in full.issues if i.severity == Severity.ERROR and i.code != "G02")
    if report.has_errors():
        return report

    service.repository.save(candidate, service.now_override)
    service.history.append(service.data)
    service.data = candidate
    return report
