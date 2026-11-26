"""SQLite lưu tài khoản, lượt đăng nhập, lịch đã chốt và đánh giá."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT NOT NULL UNIQUE,
    full_name       TEXT NOT NULL,
    email           TEXT,
    user_group      TEXT,
    role            TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','admin')),
    password_hash   TEXT NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until    TEXT,
    created_at      TEXT NOT NULL,
    last_login_at   TEXT,
    login_count     INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS login_events(
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS finalized_schedules(
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    schedule_key TEXT NOT NULL,
    week_start   TEXT,
    complete     INTEGER NOT NULL DEFAULT 0,
    used_conflict_options INTEGER NOT NULL DEFAULT 0,
    at           TEXT NOT NULL,
    UNIQUE(user_id, schedule_key)
);
CREATE TABLE IF NOT EXISTS ratings(
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    schedule_key   TEXT NOT NULL,
    week_start     TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    overall        INTEGER NOT NULL,
    nps            INTEGER,
    adoption       TEXT,
    vs_manual      INTEGER,
    conflict_clarity INTEGER,
    criteria_json  TEXT NOT NULL,
    tradeoffs_json TEXT NOT NULL,
    problems_json  TEXT NOT NULL,
    metrics_json   TEXT NOT NULL,
    comment_good   TEXT,
    comment_improve TEXT,
    UNIQUE(user_id, schedule_key)
);
CREATE INDEX IF NOT EXISTS idx_ratings_user ON ratings(user_id);
CREATE INDEX IF NOT EXISTS idx_login_events_at ON login_events(at);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_db_path() -> Path:
    configured = os.environ.get("SCHEDULE_PORTAL_DB")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "apps" / "streamlit" / "data" / "portal.db"


@contextmanager
def connect(path: Path | None = None):
    target = Path(path) if path else default_db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema(path: Path | None = None) -> None:
    with connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
