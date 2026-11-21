"""NORMALIZER: raw form data (repeating fixed tasks, deadlines with attend/progress...) -> one concrete week.

Input  (dict, what the Streamlit form collects):
  week_start "YYYY-MM-DD" (a Monday, 00:00) | now "YYYY-MM-DD HH:MM"
  fixed:     [{name, days:[0..6], start "HH:MM", end "HH:MM", type: study|meal|leisure|sleep|other,
               prep_min (0 = none), min_duration_min (optional: shortest it may be shrunk to),
               removable (optional: true = may be deleted when a deadline task conflicts)}]
  deadlines: [{name, mode: attend|progress, kind: asap|hard|soft, date "YYYY-MM-DD", time "HH:MM",
               duration_min (attend) | estimate_min / estimate_h (progress), start "now" | "YYYY-MM-DD HH:MM",
               whole: true = one single block (cửa sổ = [start, date time]), e.g. chạy bộ 1h trong 16h-18h,
               focus: high|low, buffer: bool, importance: 1..10 (optional), prep_min (attend, optional)}]
Output : Instance (everything in integer minutes since Monday 00:00) + list of Issue (ERROR / ASK / WARN).
Rules  : sleep is mandatory (it defines the day window, so nothing is planned at 2-3am); attend -> Fixed;
         a repeating fixed task becomes one interval per day; an interval crossing midnight is split;
         prep/travel time becomes its own blocked interval; a past deadline asks the user (keep -> Soft).
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, List, Optional, Tuple

from .models import DAY, STEP, WEEK, Config, Fixed, Task
from .timeline import ceil_step

DOW = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
FIXED_TYPES = {"study", "meal", "leisure", "sleep", "other"}
KINDS = {"asap", "hard", "soft"}
FOCUS_CHUNKS = {"high": (45, 90), "low": (30, 120)}                  # focus -> (min_chunk, max_chunk)
BUFFER_MIN = 15
KIND_HELP = {"asap": "ASAP: có hạn, nhưng muốn làm xong sớm nhất có thể",
             "hard": "HARD: hạn cứng, trễ là hỏng, không bao giờ tự bị bỏ",
             "soft": "SOFT: nên làm, nhưng có thể dời hoặc bỏ nếu quá tải"}


@dataclass
class Issue:
    level: str                     # ERROR (cannot continue) | ASK (user must answer) | WARN (info)
    code: str
    where: str
    message: str


@dataclass
class Instance:
    week_start: dt.date
    now: int
    tasks: List[Task]
    fixed: List[Fixed]
    cfg: Config
    names: Dict[str, str] = field(default_factory=dict)


def hm(m: int, ws: Optional[dt.date] = None) -> str:
    d, r = divmod(max(0, m), DAY)
    day = DOW[min(d, 6)] + (f" {(ws + dt.timedelta(days=d)).strftime('%d/%m')}" if ws else "")
    return f"{day} {r // 60:02d}:{r % 60:02d}"


def _hhmm(s: str) -> int:
    h, m = s.strip().split(":")
    v = int(h) * 60 + int(m)
    if not 0 <= v <= DAY:
        raise ValueError(s)
    return v


def _minutes(ws: dt.date, text: str) -> int:
    d = dt.datetime.fromisoformat(text.strip().replace("T", " "))
    return int((d - dt.datetime.combine(ws, dt.time())).total_seconds() // 60)


def normalize(raw: dict, answers: Optional[dict] = None,
              estimator: Optional[Callable[[dict], int]] = None) -> Tuple[Optional[Instance], List[Issue]]:
    """answers: {deadline index or name: "keep" | "drop"} for past-deadline questions.
       estimator: optional AI hook, called when a progress task has no estimate -> minutes (user still confirms)."""
    answers, issues = answers or {}, []

    def err(code, where, msg): issues.append(Issue("ERROR", code, where, msg))
    def warn(code, where, msg): issues.append(Issue("WARN", code, where, msg))

    # ---- week + now ----------------------------------------------------------------
    try:
        ws = dt.date.fromisoformat(raw["week_start"])
    except (KeyError, ValueError):
        return None, [Issue("ERROR", "WEEK_START", "week_start", "Ngày bắt đầu tuần không hợp lệ (YYYY-MM-DD).")]
    if ws.weekday() != 0:
        err("WEEK_START_NOT_MONDAY", "week_start", f"{ws} không phải Thứ Hai. Tuần phải bắt đầu từ Thứ Hai 00:00.")
    try:
        now = _minutes(ws, raw["now"])
    except (KeyError, ValueError):
        err("NOW", "now", "Thời gian hiện tại không hợp lệ (YYYY-MM-DD HH:MM).")
        now = 0
    if now >= WEEK:
        err("WEEK_OVER", "now", "Tuần này đã kết thúc, hãy chọn tuần khác.")
    now = ceil_step(max(0, now))                       # nothing is placed before "now"

    # ---- fixed tasks: expand repeats, split midnight, prep blocks, sleep -------------------
    fixed: List[Fixed] = []
    night_sleep: List[Tuple[int, int, int]] = []         # (day, wake, bed)
    for i, f in enumerate(raw.get("fixed", [])):
        where, name = f"fixed[{i}]", (f.get("name") or "").strip()
        typ = f.get("type", "other")
        try:
            s, e = _hhmm(f["start"]), _hhmm(f["end"])
        except (KeyError, ValueError):
            err("FIXED_TIME", where, f"«{name}»: khung giờ không hợp lệ (HH:MM, thang 24h).")
            continue
        days = sorted(set(f.get("days") or []))
        if not name or typ not in FIXED_TYPES or not days or any(d not in range(7) for d in days) or s == e:
            err("FIXED_FIELDS", where, f"«{name or '?'}»: cần tên, loại hợp lệ, ít nhất một thứ trong tuần và giờ bắt đầu ≠ giờ kết thúc.")
            continue
        prep, mn = int(f.get("prep_min") or 0), f.get("min_duration_min")
        back = int(f.get("after_min") or 0)               # travel home / wrap-up after the event
        rem = bool(f.get("removable"))                    # prep/after đi cùng sự kiện: xóa cùng nhau
        for d in days:
            if typ == "sleep" and (e < s or s < 360):      # overnight sleep -> defines the day window
                night_sleep.append((d, e, DAY if e > s else s))
                continue
            pieces = [(d * DAY + s, d * DAY + e)] if e > s else [(d * DAY + s, (d + 1) * DAY)] + \
                     ([((d + 1) * DAY, (d + 1) * DAY + e)] if d < 6 else [])
            for k, (a, b) in enumerate(pieces):
                fixed.append(Fixed(f"F{i + 1}@{d}.{k}", name, a, b, mn if len(pieces) == 1 else None, typ, rem))
            if prep > 0:
                fixed.append(Fixed(f"F{i + 1}@{d}.prep", f"{name} (chuẩn bị/di chuyển)",
                                   max(0, pieces[0][0] - prep), pieces[0][0], None, "prep", rem))
            if back > 0:
                fixed.append(Fixed(f"F{i + 1}@{d}.back", f"{name} (di chuyển về)",
                                   pieces[-1][1], min(WEEK, pieces[-1][1] + back), None, "prep", rem))

    if not night_sleep:
        err("SLEEP_MISSING", "fixed", "Bắt buộc có lịch NGỦ NGHỈ qua đêm (ví dụ 23:00–06:30) để hệ thống không xếp task vào giờ ngủ.")
        wake, bed = 7 * 60, 23 * 60
    else:
        wake, bed = max(w for _, w, _ in night_sleep), min(b for _, _, b in night_sleep)
        if len({d for d, _, _ in night_sleep}) < 7:
            warn("SLEEP_PARTIAL", "fixed", "Lịch ngủ chưa đủ 7 ngày; hệ thống dùng khung giờ thức chung cho cả tuần.")
        if bed - wake < 360:
            err("SLEEP_TOO_LONG", "fixed", f"Khung giờ thức chỉ còn {bed - wake} phút/ngày, quá ngắn để xếp lịch.")
    cfg = replace(Config(**(raw.get("config") or {})), day_start=wake // STEP * STEP, day_end=bed // STEP * STEP)

    # ---- deadlines ----------------------------------------------------------------------------
    tasks: List[Task] = []
    names: Dict[str, str] = {}
    for i, t in enumerate(raw.get("deadlines", [])):
        where, name = f"deadlines[{i}]", (t.get("name") or "").strip()
        if not name:
            err("DEADLINE_NAME", where, "Thiếu tên task.")
            continue
        try:
            D = _minutes(ws, f"{t['date']} {t['time']}")
        except (KeyError, ValueError):
            err("DEADLINE_TIME", where, f"«{name}»: hạn (ngày, giờ) không hợp lệ.")
            continue
        if t.get("mode", "progress") == "attend":          # an event, not work: becomes a fixed task
            dur = int(t.get("duration_min") or 0)
            if dur <= 0:
                err("ATTEND_DURATION", where, f"«{name}»: nhập thời lượng tham gia (phút).")
            elif D + dur <= now:
                warn("ATTEND_PAST", where, f"«{name}» đã diễn ra, bỏ qua.")
            elif D >= WEEK or D < 0:
                warn("ATTEND_OUTSIDE", where, f"«{name}» nằm ngoài tuần này, bỏ qua.")
            else:
                fixed.append(Fixed(f"A{i + 1}", name, D, min(D + dur, WEEK), None, "attend"))
                prep = int(t.get("prep_min") or 0)
                if prep > 0:
                    fixed.append(Fixed(f"A{i + 1}.prep", f"{name} (chuẩn bị/di chuyển)", max(0, D - prep), D, None, "prep"))
            continue
        kind = t.get("kind")
        focus = t.get("focus", "low")
        if kind not in KINDS or focus not in FOCUS_CHUNKS:
            err("DEADLINE_FIELDS", where, f"«{name}»: loại deadline phải là asap/hard/soft và mức tập trung high/low.")
            continue
        est = t.get("estimate_min") or (round(float(t["estimate_h"]) * 60) if t.get("estimate_h") else 0)
        if not est and estimator:
            est = int(estimator(t))
        if est <= 0:
            err("ESTIMATE", where, f"«{name}»: thiếu thời gian ước lượng (tự nhập, hoặc gửi bài để AI gợi ý).")
            continue
        est = math.ceil(est / STEP) * STEP
        try:
            start = now if str(t.get("start", "now")) == "now" else _minutes(ws, t["start"])
        except ValueError:
            err("DEADLINE_START", where, f"«{name}»: thời điểm bắt đầu không hợp lệ.")
            continue
        start = max(start, now)
        if D < now:                                         # the deadline is already behind us
            ans = answers.get(i, answers.get(name))
            if ans == "keep":
                kind, D = "soft", WEEK
                warn("PAST_KEPT", where, f"«{name}» quá hạn: chuyển thành SOFT, làm khi còn chỗ trống.")
            elif ans == "drop":
                warn("PAST_DROPPED", where, f"«{name}» quá hạn: đã bỏ.")
                continue
            else:
                issues.append(Issue("ASK", "PAST_DEADLINE", where,
                                    f"«{name}» có hạn {hm(D, ws)} đã qua. Bạn vẫn muốn làm không? "
                                    f"Có → chuyển thành SOFT (answers[{i}]='keep'); Không → nhập lại hoặc bỏ (answers[{i}]='drop')."))
                continue
        if D <= start:
            err("DEADLINE_BEFORE_START", where, f"«{name}»: hạn {hm(D, ws)} không sau thời điểm bắt đầu {hm(start, ws)}.")
            continue
        if D > WEEK:
            warn("DEADLINE_OUTSIDE", where, f"«{name}»: hạn nằm sau tuần này, chỉ xếp phần nằm trong tuần.")
        mn, mx = FOCUS_CHUNKS[focus]
        whole = bool(t.get("whole"))                        # one single block of exactly `est` minutes, no break
        if whole:
            mn = mx = est
        tid = f"D{i + 1}"
        names[tid] = name
        tasks.append(Task(tid, name, kind, int(t.get("importance") or 5), D, est, focus, mn, mx,
                          BUFFER_MIN if t.get("buffer") else 0, start, no_break=whole))

    # ---- fixed events must not overlap (prep blocks too: "no time to travel") -----------------------------
    live = sorted((f for f in fixed if f.end > now), key=lambda f: (f.start, f.end))
    for a, b in ((x, y) for k, x in enumerate(live) for y in live[k + 1:] if y.start < x.end):
        prepish = "prep" in (a.type, b.type)
        why = "Không đủ thời gian chuẩn bị/di chuyển: " if prepish else "Hai lịch cố định trùng giờ: "
        err("FIXED_OVERLAP", "fixed", f"{why}«{a.name}» ({hm(a.start, ws)}–{hm(a.end, ws)[-5:]}) "
            f"và «{b.name}» ({hm(b.start, ws)}–{hm(b.end, ws)[-5:]}).")

    names.update({f.id: f.name for f in fixed})
    if any(i.level == "ERROR" for i in issues):
        return None, issues
    return Instance(ws, now, tasks, sorted(fixed, key=lambda f: f.start), cfg, names), issues
