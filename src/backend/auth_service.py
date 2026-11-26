"""Đăng ký / đăng nhập (bảng users). Mật khẩu băm bằng bcrypt."""
from __future__ import annotations

import re

import bcrypt
import pymysql

from .db import db_readonly, db_transaction
from .errors import AuthError, BackendError, NotFoundError, UsernameTakenError

ROLES = ("student", "worker", "other")
_USERNAME_RE = re.compile(r"^[\w.@+\-]{3,100}$", re.UNICODE)


def _public(row: dict) -> dict:
    return {"id": row["id"], "username": row["username"],
            "display_name": row["display_name"] or row["username"],
            "role_group": row["role_group"]}


def register(username: str, password: str, display_name: str | None = None,
             role_group: str = "student") -> dict:
    username = (username or "").strip()
    if not _USERNAME_RE.fullmatch(username):
        raise BackendError("Tên đăng nhập 3–100 ký tự, chỉ gồm chữ, số và . _ @ + -")
    if len(password or "") < 4:
        raise BackendError("Mật khẩu tối thiểu 4 ký tự.")
    if len(password.encode("utf-8")) > 72:
        raise BackendError("Mật khẩu quá dài (tối đa 72 byte).")
    if role_group not in ROLES:
        raise BackendError("Nhóm người dùng không hợp lệ.")
    display = (display_name or "").strip()[:120] or None
    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    try:
        with db_transaction() as cur:
            cur.execute(
                "INSERT INTO users (username, password_hash, display_name, role_group) "
                "VALUES (%s, %s, %s, %s)", (username, pw_hash, display, role_group))
            user_id = cur.lastrowid
    except pymysql.err.IntegrityError as exc:
        if exc.args and exc.args[0] == 1062:
            raise UsernameTakenError("Tên đăng nhập đã tồn tại.") from exc
        raise
    return {"id": user_id, "username": username, "display_name": display or username,
            "role_group": role_group}


def login(username: str, password: str) -> dict:
    with db_readonly() as cur:
        cur.execute("SELECT id, username, password_hash, display_name, role_group "
                    "FROM users WHERE username = %s", ((username or "").strip(),))
        row = cur.fetchone()
    ok = bool(row) and bcrypt.checkpw((password or "").encode("utf-8")[:72],
                                      row["password_hash"].encode("utf-8"))
    if not ok:
        raise AuthError("Sai tên đăng nhập hoặc mật khẩu.")
    return _public(row)


def get_user(user_id: int) -> dict:
    with db_readonly() as cur:
        cur.execute("SELECT id, username, display_name, role_group FROM users WHERE id = %s",
                    (int(user_id),))
        row = cur.fetchone()
    if not row:
        raise NotFoundError("Người dùng không tồn tại.")
    return _public(row)
