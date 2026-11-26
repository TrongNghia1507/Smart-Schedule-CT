"""Các lỗi nghiệp vụ của backend. UI bắt BackendError và hiển thị `message`."""
from __future__ import annotations


class BackendError(Exception):
    code = "BACKEND_ERROR"

    def __init__(self, message: str = "", *, details: list | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or []

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "details": self.details}


class AuthError(BackendError):
    code = "UNAUTHORIZED"


class UsernameTakenError(BackendError):
    code = "USERNAME_TAKEN"


class NotFoundError(BackendError):
    """Tài nguyên không tồn tại HOẶC không thuộc user hiện tại (không phân biệt, tránh lộ thông tin)."""

    code = "NOT_FOUND"

    def __init__(self, message: str = "Không tìm thấy dữ liệu."):
        super().__init__(message)


class InputInvalidError(BackendError):
    """Dữ liệu nhập có lỗi mức Error. `details` là danh sách issue dạng dict."""

    code = "INPUT_INVALID"

    def __init__(self, details: list | None = None,
                 message: str = "Dữ liệu chưa hợp lệ, hãy sửa các lỗi trước khi tiếp tục."):
        super().__init__(message, details=details)


class InvalidWeekError(BackendError):
    code = "WEEK_START_NOT_MONDAY"

    def __init__(self, message: str = "Tuần lập lịch phải bắt đầu vào Thứ Hai."):
        super().__init__(message)


class WeekAlreadyOverError(BackendError):
    code = "WEEK_OVER"

    def __init__(self, message: str = "Tuần này đã kết thúc, hãy chọn tuần lập lịch mới."):
        super().__init__(message)


class CannotPlanError(BackendError):
    code = "CANNOT_PLAN"


class TaskNotUnscheduledError(BackendError):
    code = "TASK_NOT_UNSCHEDULED"


class AlreadyAppliedError(BackendError):
    code = "ALREADY_APPLIED"


class StaleVersionError(BackendError):
    code = "STALE_VERSION"


class OptionNotApplicableError(BackendError):
    code = "OPTION_NOT_APPLICABLE"


class FeedbackInvalidError(BackendError):
    code = "FEEDBACK_INVALID"


def issue_dict(code: str, severity: str, field: str, task_code: str, message: str) -> dict:
    return {"code": code, "severity": severity, "field": field,
            "task_code": task_code, "message": message}
