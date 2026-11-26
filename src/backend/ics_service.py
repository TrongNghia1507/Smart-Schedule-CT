"""Xuất lịch đã xếp ra file iCalendar (.ics) để thêm vào Google / Apple / Outlook Calendar."""
from __future__ import annotations

from datetime import datetime, timezone

from .db import db_readonly
from .errors import NotFoundError

_TZ_BLOCK = [
    "BEGIN:VTIMEZONE", "TZID:Asia/Ho_Chi_Minh",
    "BEGIN:STANDARD", "DTSTART:19700101T000000", "TZOFFSETFROM:+0700", "TZOFFSETTO:+0700",
    "TZNAME:ICT", "END:STANDARD", "END:VTIMEZONE",
]


def _escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def _fold(line: str) -> list[str]:
    """Gập dòng dài hơn 75 byte theo RFC 5545 (dòng tiếp theo bắt đầu bằng 1 dấu cách)."""
    data = line.encode("utf-8")
    if len(data) <= 75:
        return [line]
    out, current, size = [], "", 0
    for ch in line:
        width = len(ch.encode("utf-8"))
        if size + width > (75 if not out else 74):
            out.append(current if not out else " " + current)
            current, size = "", 0
        current += ch
        size += width
    out.append(current if not out else " " + current)
    return out


def export_schedule_ics(user_id: int, schedule_id: int) -> tuple[str, str]:
    """Trả (tên_file, nội_dung). Chỉ xuất khối việc có hạn chót và việc cố định."""
    with db_readonly() as cur:
        cur.execute("SELECT week_start FROM schedules WHERE id=%s AND user_id=%s",
                    (schedule_id, int(user_id)))
        sched = cur.fetchone()
        if not sched:
            raise NotFoundError()
        cur.execute("SELECT id, block_kind, title, start_datetime, end_datetime FROM schedule_blocks "
                    "WHERE schedule_id=%s AND block_kind IN ('deadline','fixed') "
                    "ORDER BY start_datetime, id", (schedule_id,))
        rows = cur.fetchall()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def fmt(value: datetime) -> str:
        return value.strftime("%Y%m%dT%H%M%S")

    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//SmartScheduleCT//VI",
             "CALSCALE:GREGORIAN", "X-WR-TIMEZONE:Asia/Ho_Chi_Minh", *_TZ_BLOCK]
    for row in rows:
        lines += ["BEGIN:VEVENT", f"UID:blk-{row['id']}-{schedule_id}@smart-schedule-ct",
                  f"DTSTAMP:{stamp}",
                  f"DTSTART;TZID=Asia/Ho_Chi_Minh:{fmt(row['start_datetime'])}",
                  f"DTEND;TZID=Asia/Ho_Chi_Minh:{fmt(row['end_datetime'])}",
                  "SUMMARY:" + _escape(row["title"]),
                  "CATEGORIES:" + ("Deadline" if row["block_kind"] == "deadline" else "Fixed"),
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    folded = [piece for line in lines for piece in _fold(line)]
    return (f"smart_schedule_{sched['week_start'].isoformat()}_s{schedule_id}.ics",
            "\r\n".join(folded) + "\r\n")
