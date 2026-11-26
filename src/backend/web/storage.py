from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path

from user_portal.auth import DEFAULT_ADMIN_PASSWORD, init_portal
from user_portal.db import connect, default_db_path as db_path
from user_portal.security import verify_password

SCHEMA = """
CREATE TABLE IF NOT EXISTS web_sessions(
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf TEXT NOT NULL,
    expires INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS web_drafts(
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    payload TEXT NOT NULL,
    colors TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS web_draft_undo(
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    state TEXT NOT NULL,
    PRIMARY KEY(user_id, revision)
);
CREATE TABLE IF NOT EXISTS web_plans(
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    draft_revision INTEGER NOT NULL,
    state TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS web_plans_user ON web_plans(user_id);
CREATE TABLE IF NOT EXISTS web_history(
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    week_start TEXT NOT NULL,
    record TEXT NOT NULL,
    PRIMARY KEY(user_id, id)
);
CREATE TABLE IF NOT EXISTS web_operations(
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    operation_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY(user_id, operation_id)
);
CREATE TABLE IF NOT EXISTS web_finalized(
    user_id INTEGER NOT NULL,
    schedule_key TEXT NOT NULL,
    week_start TEXT NOT NULL,
    metrics TEXT NOT NULL,
    PRIMARY KEY(user_id, schedule_key),
    FOREIGN KEY(user_id, schedule_key) REFERENCES finalized_schedules(user_id, schedule_key) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS web_legacy_history_imports(
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    history_id TEXT NOT NULL,
    PRIMARY KEY(user_id, history_id)
);
"""


def secure_cookies() -> bool:
    return os.environ.get("SCHEDULE_SECURE_COOKIE", "").lower() in {"true", "1", "yes"}


def initialize(path: Path | None = None) -> None:
    path = path or db_path()
    init_portal(path, require_configured_password=secure_cookies())
    with connect(path) as conn:
        if secure_cookies():
            admin = conn.execute("SELECT password_hash FROM users WHERE role='admin'").fetchone()
            if verify_password(DEFAULT_ADMIN_PASSWORD, admin["password_hash"]):
                raise RuntimeError("Đổi mật khẩu admin mặc định trước khi bật HTTPS.")
        conn.executescript(SCHEMA)


@contextmanager
def database(*, write: bool = False):
    with connect(db_path()) as conn:
        conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield conn


def encode(data) -> str:
    return json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
