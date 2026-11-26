"""Cấu hình backend từ biến môi trường hoặc .env."""
from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class BackendSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    db_host: str = "127.0.0.1"
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
