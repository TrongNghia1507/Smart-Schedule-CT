"""Cấu hình backend từ biến môi trường hoặc .env."""
from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class BackendSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    db_host: str = ""
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = "root"
    db_name: str = "smart_schedule_ct"
    db_ssl: bool = False
    db_ssl_ca: str = ""

    admin_password: str = "change-me-admin-2026"
    cpsat_workers: int = 2

    def resolved_ssl_ca(self) -> str:
        if self.db_ssl_ca:
            return self.db_ssl_ca
        try:
            import certifi

            return certifi.where()
        except ImportError:
            return ""


@lru_cache
def get_backend_settings() -> BackendSettings:
    settings = BackendSettings()
    os.environ.setdefault("CPSAT_WORKERS", str(settings.cpsat_workers))
    return settings
def is_mysql_enabled() -> bool:
    """Trả True khi chạy với MySQL / TiDB Cloud thay vì SQLite cục bộ."""
    if os.environ.get("SCHEDULE_FORCE_SQLITE", "").lower() in {"1", "true", "yes"}:
        return False
    if os.environ.get("SCHEDULE_PORTAL_DB"):
        return False
    # Trong lúc chạy pytest, test_web_migration gán SCHEDULE_WEB_DATA_DIR vào tmp_path
    # mà không đặt DB_HOST trên os.environ -> giữ nguyên SQLite cho unit test an toàn.
    web_dir = os.environ.get("SCHEDULE_WEB_DATA_DIR")
    if web_dir and web_dir != "/data" and not os.environ.get("DB_HOST"):
        return False
    host = os.environ.get("DB_HOST")
    if host is not None:
        return bool(host.strip())
    return bool(get_backend_settings().db_host.strip())
