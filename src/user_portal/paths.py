"""Thư mục dữ liệu riêng cho từng người dùng (nháp nhập liệu, màu, lịch sử lịch)."""
from __future__ import annotations

import os
from pathlib import Path


def streamlit_data_dir() -> Path:
    configured = os.environ.get("SCHEDULE_INPUT_DATA_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "apps" / "streamlit" / "data"


def user_data_dir(user_id: int) -> Path:
    return streamlit_data_dir() / "users" / f"u{int(user_id)}"


def user_history_path(user_id: int) -> Path:
    return user_data_dir(user_id) / "schedule_history.json"
