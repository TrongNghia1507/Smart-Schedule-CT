"""MySQLTaskRepository: thay JsonFileRepository + calendar_colors.json cho trang Nhập liệu.

Cùng giao diện với repository cũ: ``load(default)`` và ``save(data, now_override)``.
Mọi truy vấn đều lọc theo user_id nên dữ liệu mỗi người tách riêng.
"""
from __future__ import annotations

import re
from datetime import date

from schedule_input.application.mapper import TaskFactory, hh
from schedule_input.domain.models import Weekday
from schedule_input.infrastructure.repositories import TaskRepository

from .clock import now_vn_naive
from .db import db_readonly, db_transaction
from .errors import InputInvalidError, InvalidWeekError, issue_dict
from .input_builder import (build_schedule_input, default_settings, fetch_week_rows)

_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_MAX_MIN = 10080


def _check_monday(week_start: date) -> None:
    if week_start.weekday() != 0:
        raise InvalidWeekError()


def _check_limits(data) -> None:
    issues = []
    for t in data.deadline_tasks:
        if t.remaining_min > _MAX_MIN:
            issues.append(issue_dict("V08", "Error", "remaining_min", t.id,
                                     f"Thời lượng tối đa {_MAX_MIN} phút."))
        if t.chunk.max_min > _MAX_MIN or t.chunk.min_min > _MAX_MIN:
            issues.append(issue_dict("V11", "Error", "chunk_max", t.id,
                                     f"Chunk tối đa {_MAX_MIN} phút."))
    if issues:
        raise InputInvalidError(issues)


def _color(value):
    return value if isinstance(value, str) and _COLOR_RE.fullmatch(value) else None


class MySQLTaskRepository(TaskRepository):
    blocked = False  # app cũ đọc thuộc tính này; DB không bao giờ ở trạng thái "bị bảo vệ"

    def __init__(self, user_id: int, week_start: date | None = None):
        self.user_id = int(user_id)
        self.week_start = week_start

    def for_week(self, week_start: date) -> "MySQLTaskRepository":
        return MySQLTaskRepository(self.user_id, week_start)

    # ------------------------------------------------------------------ đọc
    def load(self, default):
        week = self.week_start or default.window.week_start
        with db_readonly() as cur:
            settings, fixed_rows, deadline_rows = fetch_week_rows(cur, self.user_id, week)
        if not settings["_exists"] and not fixed_rows and not deadline_rows:
            return default, None, []
        try:
            data, issues = build_schedule_input(week, settings, fixed_rows, deadline_rows,
                                                now_vn_naive())
        except InputInvalidError as exc:
            return default, None, ["Thiết lập tuần không hợp lệ: " +
                                   "; ".join(d["message"] for d in exc.details)]
        notes = [f"Không đọc được bản ghi: {i.task_id} ({i.message})" for i in issues
                 if not isinstance(i, dict)] + \
                [f"Không đọc được bản ghi: {i['task_code']} ({i['message']})" for i in issues
                 if isinstance(i, dict)]
        return data, None, notes

    # ------------------------------------------------------------------ ghi
    def save(self, data, now_override=None, colors: dict | None = None) -> None:
        week = data.window.week_start
        _check_monday(week)
        _check_limits(data)
        sleep = data.window.sleep
        fixed_rows, deadline_rows = [], []
        with db_transaction() as cur:
            cur.execute(
                "INSERT INTO user_week_settings (user_id, week_start, sleep_start, sleep_end) "
                "VALUES (%s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE sleep_start=VALUES(sleep_start), "
                "sleep_end=VALUES(sleep_end)",
                (self.user_id, week, hh(sleep.start), hh(sleep.end)))
            cur.execute("SELECT task_code, display_color FROM fixed_tasks "
                        "WHERE user_id=%s AND week_start=%s AND display_color IS NOT NULL",
                        (self.user_id, week))
            kept = {r["task_code"]: r["display_color"] for r in cur.fetchall()}
            for code, value in (colors or {}).items():
                kept[code] = value
            cur.execute("DELETE FROM fixed_tasks WHERE user_id=%s AND week_start=%s",
                        (self.user_id, week))
            cur.execute("DELETE FROM deadline_tasks WHERE user_id=%s AND week_start=%s",
                        (self.user_id, week))
            for t in data.fixed_tasks:
                days = [d.value for d in Weekday if d in t.repeat.days]
                fixed_rows.append((
                    self.user_id, week, t.id, t.name, ",".join(days) or None,
                    t.repeat.one_off_date, hh(t.time_range.start), hh(t.time_range.end),
                    t.prep_min, t.after_min, 1 if t.removable else 0, _color(kept.get(t.id))))
            for t in data.deadline_tasks:
                deadline_rows.append((
                    self.user_id, week, t.id, t.name, 1 if t.mandatory else 0, t.importance,
                    t.deadline, t.remaining_min, t.focus.value, t.buffer.minutes,
                    t.earliest_start, t.chunk.min_min, t.chunk.max_min))
            if fixed_rows:
                cur.executemany(
                    "INSERT INTO fixed_tasks (user_id, week_start, task_code, name, repeat_days, "
                    "one_off_date, start_time, end_time, prep_min, after_min, "
                    "removable_when_busy, display_color) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", fixed_rows)
            if deadline_rows:
                cur.executemany(
                    "INSERT INTO deadline_tasks (user_id, week_start, task_code, name, mandatory, "
                    "importance, deadline, remaining_min, focus, buffer_min, earliest_start, "
                    "chunk_min, chunk_max) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    deadline_rows)

    # ------------------------------------------------- tiện ích cho UI cũ
    def to_dict_rows(self, data):
        return ([TaskFactory.to_dict(t) for t in data.fixed_tasks],
                [TaskFactory.to_dict(t) for t in data.deadline_tasks])


# ----------------------------------------------------------- màu hiển thị
def load_task_colors(user_id: int, week_start: date) -> dict:
    with db_readonly() as cur:
        cur.execute("SELECT task_code, display_color FROM fixed_tasks "
                    "WHERE user_id=%s AND week_start=%s AND display_color IS NOT NULL",
                    (int(user_id), week_start))
        return {r["task_code"]: r["display_color"] for r in cur.fetchall()}


def save_task_color(user_id: int, week_start: date, task_code: str, color: str | None) -> None:
    """color=None để về màu mặc định. Chỉ áp dụng cho việc cố định."""
    with db_transaction() as cur:
        cur.execute("UPDATE fixed_tasks SET display_color=%s "
                    "WHERE user_id=%s AND week_start=%s AND task_code=%s",
                    (_color(color), int(user_id), week_start, task_code))


# -------------------------------------------------------- thiết lập tuần
def get_week_settings(user_id: int, week_start: date) -> dict:
    with db_readonly() as cur:
        settings, _, _ = fetch_week_rows(cur, int(user_id), week_start)
    return {k: settings[k] for k in ("sleep_start", "sleep_end", "max_earlier_min", "max_later_min")}


def save_week_settings(user_id: int, week_start: date, sleep_start: str | None = None,
                       sleep_end: str | None = None, max_earlier_min: int | None = None,
                       max_later_min: int | None = None) -> dict:
    _check_monday(week_start)
    current = get_week_settings(user_id, week_start)
    merged = {
        "sleep_start": sleep_start if sleep_start is not None else current["sleep_start"],
        "sleep_end": sleep_end if sleep_end is not None else current["sleep_end"],
        "max_earlier_min": current["max_earlier_min"] if max_earlier_min is None else int(max_earlier_min),
        "max_later_min": current["max_later_min"] if max_later_min is None else int(max_later_min),
    }
    for key in ("max_earlier_min", "max_later_min"):
        if not 0 <= merged[key] <= 60:
            raise InputInvalidError([issue_dict("S02", "Error", key, "", "Mức nới tối đa từ 0 đến 60 phút.")])
    # kiểm tra giờ ngủ bằng chính bộ parse của lõi
    build_schedule_input(week_start, {**merged, "week_start": week_start}, [], [], now_vn_naive())
    with db_transaction() as cur:
        cur.execute(
            "INSERT INTO user_week_settings (user_id, week_start, sleep_start, sleep_end, "
            "max_earlier_min, max_later_min) VALUES (%s,%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE sleep_start=VALUES(sleep_start), sleep_end=VALUES(sleep_end), "
            "max_earlier_min=VALUES(max_earlier_min), max_later_min=VALUES(max_later_min)",
            (int(user_id), week_start, merged["sleep_start"], merged["sleep_end"],
             merged["max_earlier_min"], merged["max_later_min"]))
    return merged
