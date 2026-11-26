"""Mốc "bây giờ" theo giờ Việt Nam (sửa lỗi bản Streamlit cũ luôn ép now = 00:00 Thứ Hai)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .errors import WeekAlreadyOverError

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def now_vn_naive() -> datetime:
    """Giờ hiện tại ở Việt Nam, không gắn tzinfo (đúng kiểu dữ liệu lõi cũ mong đợi)."""
    return datetime.now(VN_TZ).replace(tzinfo=None, second=0, microsecond=0)


def effective_planning_now(week_start: date) -> datetime:
    """Tuần tương lai: tính từ 00:00 Thứ Hai. Tuần hiện tại: giữ giờ thật để không xếp lùi
    vào quá khứ. Tuần đã qua: báo lỗi."""
    current = now_vn_naive()
    monday = datetime.combine(week_start, time.min)
    if current < monday:
        return monday
    if current >= monday + timedelta(days=7):
        raise WeekAlreadyOverError()
    return current


def lenient_now(week_start: date) -> datetime:
    """Như effective_planning_now nhưng tuần đã qua vẫn trả 00:00 Thứ Hai (dùng khi chỉ lưu/xem)."""
    try:
        return effective_planning_now(week_start)
    except WeekAlreadyOverError:
        return datetime.combine(week_start, time.min)
