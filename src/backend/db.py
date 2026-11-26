"""Kết nối MySQL / TiDB Cloud bằng PyMySQL và helper transaction."""
from __future__ import annotations

from contextlib import contextmanager

import pymysql
from pymysql.cursors import DictCursor

from .config import get_backend_settings


def get_connection(*, with_database: bool = True):
    cfg = get_backend_settings()
    ssl_params = None
    if cfg.db_ssl:
        ca = cfg.resolved_ssl_ca()
        ssl_params = {"ca": ca} if ca else {}
    return pymysql.connect(
        host=cfg.db_host,
        port=cfg.db_port,
        user=cfg.db_user,
        password=cfg.db_password,
        database=cfg.db_name if with_database else None,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        ssl=ssl_params,
        connect_timeout=10,
        read_timeout=60,
        write_timeout=60,
    )


@contextmanager
def db_transaction():
    """Thao tác GHI: tự commit khi xong, tự rollback khi có lỗi."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def db_readonly():
    """Thao tác CHỈ ĐỌC. Đóng kết nối ngay trước khi chạy CP-SAT (vài giây đến vài chục giây)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            yield cur
    finally:
        conn.close()


def ping() -> bool:
    try:
        with db_readonly() as cur:
            cur.execute("SELECT 1 AS ok")
            return cur.fetchone()["ok"] == 1
    except Exception:
        return False
