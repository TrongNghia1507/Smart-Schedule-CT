"""Lớp kết nối CSDL kép: tự động dùng MySQL / TiDB Cloud khi có DB_HOST, hoặc SQLite khi chạy cục bộ / test."""
from __future__ import annotations

import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from backend.config import is_mysql_enabled
from backend.db import get_connection as get_mysql_connection
from backend.init_db import apply_schema

MYSQL_SENTINEL = "__mysql__"

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

_USER_MIGRATIONS = (
    "ALTER TABLE users ADD COLUMN full_name VARCHAR(120) NOT NULL DEFAULT ''",
    "ALTER TABLE users ADD COLUMN display_name VARCHAR(120) DEFAULT NULL",
    "ALTER TABLE users ADD COLUMN email VARCHAR(255) DEFAULT NULL",
    "ALTER TABLE users ADD COLUMN user_group VARCHAR(80) DEFAULT NULL",
    "ALTER TABLE users ADD COLUMN role VARCHAR(16) NOT NULL DEFAULT 'user'",
    "ALTER TABLE users ADD COLUMN failed_attempts INT NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN locked_until VARCHAR(40) DEFAULT NULL",
    "ALTER TABLE users ADD COLUMN last_login_at VARCHAR(40) DEFAULT NULL",
    "ALTER TABLE users ADD COLUMN login_count INT NOT NULL DEFAULT 0",
    "ALTER TABLE users MODIFY COLUMN created_at VARCHAR(40) NOT NULL",
)


class CompatRow(dict):
    """Tương thích với sqlite3.Row: truy cập được cả row['col'], dict(row) lẫn row[0], row[1:]."""

    def __init__(self, mapping: dict):
        normalized = {}
        for k, v in mapping.items():
            if isinstance(v, datetime) and k in {"created_at", "updated_at", "last_login_at", "at"}:
                v = v.replace(tzinfo=timezone.utc).isoformat(timespec="seconds")
            normalized[k] = v
        super().__init__(normalized)
        self._seq = tuple(normalized.values())

    def __getitem__(self, key):
        if isinstance(key, (int, slice)):
            return self._seq[key]
        return super().__getitem__(key)


class _NoopCursor:
    rowcount = 0
    lastrowid = None

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def __iter__(self):
        return iter(())


class MySQLCompatCursor:
    def __init__(self, raw_cursor):
        self._cur = raw_cursor

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount

    @property
    def lastrowid(self):
        return self._cur.lastrowid

    def fetchone(self):
        row = self._cur.fetchone()
        return CompatRow(row) if row is not None else None

    def fetchall(self):
        return [CompatRow(r) for r in self._cur.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


def _translate_sqlite_to_mysql(sql: str) -> str:
    s = sql.strip()
    s = re.sub(r"(?i)\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT IGNORE INTO", s)
    s = re.sub(r"(?i)ON\s+CONFLICT\s*\([^)]*\)\s*DO\s+UPDATE\s+SET", "ON DUPLICATE KEY UPDATE", s)
    s = re.sub(r"(?i)\bexcluded\.(\w+)", r"VALUES(\1)", s)
    s = re.sub(r"(?i)\browid\b", "seq", s)
    s = s.replace("?", "%s")
    return s


class MySQLCompatConnection:
    """Bọc kết nối PyMySQL để dùng cùng cú pháp conn.execute(...) với SQLite."""

    is_mysql = True

    def __init__(self, raw_conn):
        self._conn = raw_conn

    def execute(self, sql: str, params=()):
        head = sql.lstrip().upper()
        if head.startswith(("BEGIN", "PRAGMA")):
            return _NoopCursor()
        translated = _translate_sqlite_to_mysql(sql)
        cur = self._conn.cursor()
        if params:
            norm_params = tuple(
                p.isoformat() if hasattr(p, "isoformat") and not isinstance(p, str) else p
                for p in params
            )
            cur.execute(translated, norm_params)
        else:
            cur.execute(translated)
        return MySQLCompatCursor(cur)

    def executescript(self, _script: str):
        # Đã khởi tạo đầy đủ bảng MySQL trong init_schema()
        return _NoopCursor()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def use_mysql(path: Path | str | None = None) -> bool:
    if path == MYSQL_SENTINEL:
        return True
    if path is not None:
        return False
    return is_mysql_enabled()


def default_db_path() -> Path | str:
    if is_mysql_enabled():
        return MYSQL_SENTINEL
    configured = os.environ.get("SCHEDULE_PORTAL_DB")
    if configured:
        return Path(configured)
    return Path(os.environ.get("SCHEDULE_WEB_DATA_DIR") or ".data") / "portal.db"


@contextmanager
def connect(path: Path | str | None = None):
    if use_mysql(path):
        raw_conn = get_mysql_connection()
        wrapper = MySQLCompatConnection(raw_conn)
        try:
            yield wrapper
            raw_conn.commit()
        except Exception:
            raw_conn.rollback()
            raise
        finally:
            raw_conn.close()
        return

    target = Path(path) if path else Path(default_db_path())
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


def init_schema(path: Path | str | None = None) -> None:
    if use_mysql(path):
        apply_schema(drop_existing=False)
        raw_conn = get_mysql_connection()
        try:
            with raw_conn.cursor() as cur:
                for stmt in _USER_MIGRATIONS:
                    try:
                        cur.execute(stmt)
                    except Exception:
                        pass
            raw_conn.commit()
        finally:
            raw_conn.close()
        return

    with connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
