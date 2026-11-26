class WebError(Exception):
    def __init__(self, status: int, code: str, message: str, issues=None):
        self.status = status
        self.code = code
        self.message = message
        self.issues = issues or []


def stale():
    return WebError(409, "STALE_VERSION", "Dữ liệu đã thay đổi. Hãy tải lại phiên bản mới nhất.")


def not_found():
    return WebError(404, "NOT_FOUND", "Không tìm thấy dữ liệu.")
