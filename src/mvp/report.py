"""Giải thích xung đột bằng ngôn ngữ thường (dùng bởi m_validate). Tách khỏi week.py để không kéo theo collision."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .models import DAY, Config, Fixed, Task
from .normalizer import DOW, hm
from .pipeline import Conflict
from .timeline import free, make_gaps


@dataclass
class ConflictReport:
    source: str                       # VALIDATE (week capacity) | SPLIT (cannot split the minutes into the days)
    deadline_text: str
    window_text: str
    demand: int
    free: int
    deficit: int
    free_by_day: List[dict]
    tasks: List[dict]                 # the tasks that compete for this window
    tip_task: str
    text: str                         # plain-language explanation for the user

    def dto(self) -> dict:
        return self.__dict__.copy()


# ----------------------------------------------------------------------------- explanations
def explain(c: Conflict, tasks: List[Task], fixed: List[Fixed], cfg: Config, now: int, ws, source: str,
            missing_work: int = 0) -> ConflictReport:
    gaps = make_gaps(fixed, cfg, now)
    byid = {t.id: t for t in tasks}
    scope = [byid[i] for i in c.scope_ids]
    a, D = c.window_start, c.deadline
    demand, fr = sum(t.footprint(cfg) for t in scope), free(gaps, a, D)
    by_day = []
    for d in range(a // DAY, (D - 1) // DAY + 1):
        lo, hi = max(a, d * DAY), min(D, (d + 1) * DAY)
        if hi > lo:
            by_day.append({"day": DOW[d], "free_min": free(gaps, lo, hi)})
    rows = [{"id": t.id, "name": t.name, "kind": t.kind, "importance": t.importance, "remaining_min": t.remaining,
             "footprint_min": t.footprint(cfg), "deadline": hm(t.deadline, ws)} for t in scope]
    tip = byid[c.task_id]
    listing = "; ".join(f"«{t['name']}» {t['footprint_min']}′" for t in rows)
    if source == "VALIDATE":
        text = (f"Đến hạn {hm(D, ws)}, các việc phải xong gồm: {listing}. Tổng cần {demand} phút "
                f"(gồm {demand - sum(t['remaining_min'] for t in rows)} phút nghỉ giữa các đoạn và buffer), "
                f"nhưng từ {hm(a, ws)} đến {hm(D, ws)} chỉ còn {fr} phút trống sau khi trừ lịch cố định, giờ ngủ và thời gian "
                f"chuẩn bị. Thiếu {c.deficit} phút. Việc làm tràn là «{tip.name}».")
    else:
        text = (f"Tổng thời gian đủ, nhưng «{tip.name}» ({tip.remaining} phút) không chia được vào các ngày cho phép: "
                f"giới hạn sức làm mỗi ngày ({cfg.daily_cap}′, việc cần tập trung cao {cfg.high_cap}′) và khoảng trống bị chia nhỏ "
                f"nên mỗi ngày chỉ nhận được một phần; còn thiếu khoảng {missing_work or c.deficit} phút.")
    return ConflictReport(source, hm(D, ws), f"{hm(a, ws)} → {hm(D, ws)}", demand, fr, c.deficit, by_day, rows, tip.name, text)


