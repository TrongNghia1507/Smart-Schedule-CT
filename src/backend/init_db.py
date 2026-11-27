"""Tạo bảng từ database/schema.sql vào DB đã cấu hình (.env / biến môi trường / st.secrets).

    python -m backend.init_db          # tạo các bảng còn thiếu
    python -m backend.init_db --drop   # XÓA toàn bộ bảng rồi tạo lại (mất dữ liệu!)
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from .config import get_backend_settings
from .db import get_connection

def _find_default_schema() -> Path:
    for candidate in (
        Path.cwd() / "database" / "schema.sql",
        Path("/app/database/schema.sql",),
        Path(__file__).resolve().parents[2] / "database" / "schema.sql",
    ):
        if candidate.exists():
            return candidate
    return Path.cwd() / "database" / "schema.sql"


DEFAULT_SCHEMA = _find_default_schema()
TABLES_DROP_ORDER = [
    "web_finalized", "web_rating_prompts", "web_legacy_history_imports", "web_operations", "web_history",
    "web_plans", "web_draft_undo", "web_drafts", "web_sessions",
    "ratings", "finalized_schedules", "login_events",
    "feedbacks", "schedule_histories", "conflict_options", "schedule_blocks",
    "schedules", "deadline_tasks", "fixed_tasks", "user_week_settings", "users",
]



def split_statements(sql_text: str) -> list[str]:
    """Bỏ chú thích '--', tách theo ';', bỏ CREATE DATABASE / USE (DB lấy từ cấu hình)."""
    cleaned = re.sub(r"--[^\n]*", "", sql_text)
    out = []
    for raw in cleaned.split(";"):
        statement = raw.strip()
        if not statement or re.match(r"(?i)^(CREATE\s+DATABASE|USE)\b", statement):
            continue
        out.append(statement)
    return out


def _ensure_database() -> None:
    cfg = get_backend_settings()
    try:  # TiDB Cloud / host free thường đã có sẵn DB và không cho tạo thêm
        conn = get_connection(with_database=False)
        try:
            with conn.cursor() as cur:
                cur.execute(f"CREATE DATABASE IF NOT EXISTS `{cfg.db_name}` "
                            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def apply_schema(schema_path: str | Path | None = None, drop_existing: bool = False) -> int:
    """Chạy schema. Trả số câu lệnh đã thực thi."""
    _ensure_database()
    text = Path(schema_path or DEFAULT_SCHEMA).read_text(encoding="utf-8")
    statements = split_statements(text)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if drop_existing:
                cur.execute("SET FOREIGN_KEY_CHECKS=0")
                for table in TABLES_DROP_ORDER:
                    cur.execute(f"DROP TABLE IF EXISTS `{table}`")
                cur.execute("SET FOREIGN_KEY_CHECKS=1")
            for statement in statements:
                if not drop_existing:
                    statement = re.sub(r"(?i)^CREATE\s+TABLE\s+", "CREATE TABLE IF NOT EXISTS ",
                                       statement, count=1)
                cur.execute(statement)
        conn.commit()
    finally:
        conn.close()
    return len(statements)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tạo bảng Smart Schedule CT")
    parser.add_argument("--drop", action="store_true", help="xóa bảng cũ trước khi tạo")
    parser.add_argument("--schema", default=None, help="đường dẫn schema.sql")
    args = parser.parse_args()
    print(f"Đã chạy {apply_schema(args.schema, args.drop)} câu lệnh.")
