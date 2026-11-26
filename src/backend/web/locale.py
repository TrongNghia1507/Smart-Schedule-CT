from contextvars import ContextVar

from .translations import tr

web_language = ContextVar("schedule_web_language", default="vi")

MESSAGES = {
    "Dữ liệu đã thay đổi. Hãy tải lại phiên bản mới nhất.": "The data has changed. Reload the latest version.",
    "Không tìm thấy dữ liệu.": "The requested data was not found.",
    "Hãy đăng nhập để tiếp tục.": "Sign in to continue.",
    "Sai tên đăng nhập hoặc mật khẩu.": "Incorrect username or password.",
    "Phiên không hợp lệ. Hãy tải lại trang.": "The session is invalid. Reload the page.",
    "Tính năng này dành cho quản trị viên.": "Administrator access required.",
    "Tính năng này dành cho tài khoản lập lịch.": "A planner account is required.",
    "Hãy kiểm tra các trường được đánh dấu.": "Check the highlighted fields.",
    "Hãy chọn ngày Thứ Hai.": "Choose a Monday.",
    "Không có thay đổi để hoàn tác.": "There is no change to undo.",
    "CSV tối đa 2 MB.": "CSV files can be up to 2 MB.",
    "CSV không có dòng hợp lệ.": "The CSV has no valid rows.",
    "Dữ liệu gửi lên không hợp lệ.": "The request contains invalid data.",
    "Hãy phân tích phương án trước khi áp dụng.": "Analyze the options before applying one.",
    "Phương án không khả dụng.": "This option is unavailable.",
    "Cần ít nhất một task có hạn để xếp lịch.": "Add at least one deadline task to run the scheduler.",
    "Mật khẩu hiện tại không đúng.": "The current password is incorrect.",
    "Mật khẩu nhập lại không khớp.": "The passwords do not match.",
}


def localize(value):
    if web_language.get() != "en" or not isinstance(value, str):
        return value
    return MESSAGES[value] if value in MESSAGES else tr(value, "en")
