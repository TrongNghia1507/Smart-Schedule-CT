"""Đăng ký và đăng nhập. Không phụ thuộc Streamlit để dễ kiểm thử."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .db import connect, init_schema, utc_now
from .security import DUMMY_HASH, hash_password, verify_password

ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "123"
MIN_PASSWORD_LEN = 6
MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 5
USER_GROUPS = ["Sinh viên", "Học sinh", "Nhân viên văn phòng", "Giảng viên / Nghiên cứu", "Làm tự do", "Khác"]
USERNAME_RE = re.compile(r"^[a-z0-9_.]{3,30}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class User:
    id: int
    username: str
    full_name: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def init_portal(path=None) -> None:
    """Tạo bảng và tài khoản admin mặc định (mật khẩu 123, đổi được bằng biến môi trường)."""
    init_schema(path)
    with connect(path) as conn:
        if conn.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
            return
        password = os.environ.get("SCHEDULE_ADMIN_PASSWORD") or DEFAULT_ADMIN_PASSWORD
        conn.execute(
            "INSERT INTO users(username, full_name, role, password_hash, created_at) "
            "VALUES (?, 'Quản trị viên', 'admin', ?, ?)",
            (ADMIN_USERNAME, hash_password(password), utc_now()),
        )


def validate_registration(username, full_name, email, password, confirm, consent) -> list[str]:
    errors = []
    if len(full_name.strip()) < 2:
        errors.append("Họ và tên cần ít nhất 2 ký tự.")
    if not USERNAME_RE.match(username):
        errors.append("Tên đăng nhập gồm 3–30 ký tự: chữ thường không dấu, số, dấu chấm hoặc gạch dưới.")
    if username == ADMIN_USERNAME:
        errors.append("Tên đăng nhập này đã được hệ thống sử dụng.")
    if email and not EMAIL_RE.match(email):
        errors.append("Email chưa đúng định dạng (có thể để trống).")
    if len(password) < MIN_PASSWORD_LEN:
        errors.append(f"Mật khẩu cần ít nhất {MIN_PASSWORD_LEN} ký tự.")
    elif password != confirm:
        errors.append("Mật khẩu nhập lại không khớp.")
    if not consent:
        errors.append("Hãy đồng ý cho hệ thống lưu đánh giá và chỉ số lịch của bạn để cải thiện thuật toán.")
    return errors


def register_user(username, full_name, email, user_group, password, confirm, consent, path=None):
    """Trả về (User, []) nếu thành công, hoặc (None, [lỗi...])."""
    username = (username or "").strip().lower()
    full_name = " ".join((full_name or "").split())
    email = (email or "").strip()
    errors = validate_registration(username, full_name, email, password or "", confirm or "", consent)
    if errors:
        return None, errors
    with connect(path) as conn:
        if conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            return None, ["Tên đăng nhập đã tồn tại, hãy chọn tên khác."]
        cursor = conn.execute(
            "INSERT INTO users(username, full_name, email, user_group, role, password_hash, created_at) "
            "VALUES (?, ?, ?, ?, 'user', ?, ?)",
            (username, full_name, email or None, user_group, hash_password(password), utc_now()),
        )
        return User(cursor.lastrowid, username, full_name, "user"), []


def _authenticate(username: str, password: str, role: str, path=None):
    """Trả về (User, None) hoặc (None, thông báo lỗi). Khoá tạm sau nhiều lần sai."""
    generic = "Sai tên đăng nhập hoặc mật khẩu."
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM users WHERE username=? AND role=?", (username, role)).fetchone()
        if row is None:
            verify_password(password, DUMMY_HASH)
            return None, generic
        now = datetime.now(timezone.utc)
        if row["locked_until"]:
            until = datetime.fromisoformat(row["locked_until"])
            if until > now:
                minutes = max(1, int((until - now).total_seconds() // 60) + 1)
                return None, f"Đăng nhập sai quá nhiều lần. Thử lại sau khoảng {minutes} phút."
        if not verify_password(password, row["password_hash"]):
            failed = row["failed_attempts"] + 1
            locked = None
            if failed >= MAX_FAILED_ATTEMPTS:
                locked = (now + timedelta(minutes=LOCK_MINUTES)).isoformat(timespec="seconds")
                failed = 0
            conn.execute("UPDATE users SET failed_attempts=?, locked_until=? WHERE id=?",
                         (failed, locked, row["id"]))
            return None, generic
        stamp = utc_now()
        conn.execute("UPDATE users SET failed_attempts=0, locked_until=NULL, last_login_at=?, "
                     "login_count=login_count+1 WHERE id=?", (stamp, row["id"]))
        conn.execute("INSERT INTO login_events(user_id, at) VALUES (?, ?)", (row["id"], stamp))
        return User(row["id"], row["username"], row["full_name"], row["role"]), None


def login_user(username, password, path=None):
    return _authenticate((username or "").strip().lower(), password or "", "user", path)


def login_admin(password, path=None):
    return _authenticate(ADMIN_USERNAME, password or "", "admin", path)


def change_admin_password(current, new, confirm, path=None) -> str | None:
    """Trả về thông báo lỗi, hoặc None nếu đổi thành công."""
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM users WHERE role='admin'").fetchone()
        if row is None or not verify_password(current or "", row["password_hash"]):
            return "Mật khẩu hiện tại không đúng."
        if len(new or "") < MIN_PASSWORD_LEN:
            return f"Mật khẩu mới cần ít nhất {MIN_PASSWORD_LEN} ký tự."
        if new != confirm:
            return "Mật khẩu nhập lại không khớp."
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new), row["id"]))
    return None
