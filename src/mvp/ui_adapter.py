"""UI -> engine.   InputSnapshot (schema 2, do khối Input tạo) -> RAW dict của mvp.normalizer.

Khối Input KHÔNG bị sửa. Mọi thứ engine cần mà snapshot chưa có (loại việc, thời gian đi/về) là KHÓA TÙY CHỌN:
nếu sau này UI thêm `type`, `prep_min`, `after_min` vào hàng việc cố định thì được chuyển thẳng sang engine.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Tuple

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
IMPORTANCE_UI_TO_ENGINE = {1: 3, 2: 6, 3: 9}          # UI 1..3  ->  engine 1..10
FIXED_TYPES = {"study", "meal", "leisure", "other"}   # "sleep" chỉ đến từ window.sleep, không từ hàng việc
STEP = 5


class SnapshotError(ValueError):
    pass


@dataclass
class TaskMeta:
    """Thông tin của 1 việc có hạn mà normalizer không mang theo được (UI cho phép nhiều hơn engine)."""
    ui_id: str
    name: str
    importance_ui: int
    buffer_min: int
    chunk_min: int
    chunk_max: int
    can_split: bool
    focus: str
    mandatory: bool = True 

@dataclass
class UiMeta:
    deadlines: Dict[str, TaskMeta] = field(default_factory=dict)      # id engine ("D1") -> meta
    fixed_ui_ids: Dict[str, str] = field(default_factory=dict)        # tiền tố id engine ("F2") -> id UI
    notes: List[str] = field(default_factory=list)

    def ui_id(self, engine_id: str) -> str:
        """id engine (D3 / F2@1.0 / F2@1.prep / A1) -> id UI nếu có"""
        if engine_id in self.deadlines:
            return self.deadlines[engine_id].ui_id
        return self.fixed_ui_ids.get(engine_id.split("@")[0].split(".")[0], engine_id)


def load_snapshot(obj: Any) -> dict:
    """InputSnapshot | dict | chuỗi JSON | đường dẫn file JSON -> dict schema 2"""
    if hasattr(obj, "to_dict"):
        data = obj.to_dict()
    elif isinstance(obj, dict):
        data = dict(obj)
    elif isinstance(obj, (str, Path)):
        text = str(obj)
        data = json.loads(text) if text.lstrip().startswith("{") else json.loads(Path(text).read_text(encoding="utf-8-sig"))
    else:
        raise SnapshotError("Snapshot phải là InputSnapshot, dict, chuỗi JSON hoặc đường dẫn file.")
    if data.get("schema_version") != 2:
        raise SnapshotError(f"Chỉ hỗ trợ snapshot schema 2 (nhận {data.get('schema_version')!r}).")
    for key in ("window", "fixed_tasks", "deadline_tasks"):
        if key not in data:
            raise SnapshotError(f"Snapshot thiếu «{key}».")
    return data


def _iso(text: str) -> str:
    return str(text).replace("T", " ")[:16]

def is_mandatory(row: dict) -> bool:
    if "mandatory" in row:
        return bool(row["mandatory"])
    return row.get("kind") != "soft"      # snapshot cũ: hard/asap = bắt buộc
def snapshot_to_raw(snapshot: Any) -> Tuple[dict, UiMeta]:
    snap = load_snapshot(snapshot)
    win = snap["window"]
    ws = dt.date.fromisoformat(win["week_start"])
    meta = UiMeta()

    # ---- việc cố định: giờ ngủ trước (engine bắt buộc có để biết khung giờ thức) -------------------------
    sleep = win.get("sleep") or {}
    fixed: List[dict] = [{"name": "Ngủ", "days": list(range(7)), "start": sleep.get("start", "23:00"),
                          "end": sleep.get("end", "05:00"), "type": "sleep"}]
    meta.fixed_ui_ids["F1"] = "sleep"
    for row in snap["fixed_tasks"]:
        if row.get("one_off_date"):
            idx = (dt.date.fromisoformat(row["one_off_date"]) - ws).days
            if not 0 <= idx < 7:
                meta.notes.append(f"«{row['name']}» diễn ra ngoài tuần, bỏ qua.")
                continue
            days = [idx]
        else:
            days = sorted(WEEKDAYS.index(d) for d in row.get("repeat_days") or [])
        item = {"name": row["name"], "days": days, "start": row["start"], "end": row["end"],
                "type": row.get("type") if row.get("type") in FIXED_TYPES else "other"}
        if row.get("is_flexible") and row.get("min_duration_min"):
            item["min_duration_min"] = int(row["min_duration_min"])
        if row.get("removable_when_busy"):
            item["removable"] = True
        for key in ("prep_min", "after_min"):                      # khóa tùy chọn, UI hiện chưa có
            if row.get(key):
                item[key] = int(row[key])
        fixed.append(item)
        meta.fixed_ui_ids[f"F{len(fixed)}"] = row["id"]

    # ---- việc có hạn ------------------------------------------------------------------------------------
    deadlines: List[dict] = []
    deadlines: List[dict] = []
    for i, row in enumerate(snap["deadline_tasks"]):
        mandatory = is_mandatory(row)
        if mandatory:
            date, _, clock = _iso(row["deadline"]).partition(" ")
        else:
            # Không bắt buộc: deadline cố định là hết Chủ nhật (= 00:00 thứ Hai tuần sau).
            date, clock = (ws + dt.timedelta(days=7)).isoformat(), "00:00"
        eff = row.get("effective_chunk") or {}
        item = {"name": row["name"], "mode": "progress",
                "kind": "hard" if mandatory else "soft",
                "date": date, "time": clock,
                "estimate_min": int(row["remaining_min"]), "focus": row.get("focus", "high"),
                "buffer": int(row.get("buffer_min") or 0) > 0,
                "importance": IMPORTANCE_UI_TO_ENGINE[int(row.get("importance") or 2)],
                "start": _iso(row["earliest_start"]) if row.get("earliest_start") else "now"}
        deadlines.append(item)
        meta.deadlines[f"D{i + 1}"] = TaskMeta(
            row["id"], row["name"], int(row.get("importance") or 2), int(row.get("buffer_min") or 0),
            int(eff.get("min") or row.get("chunk_min") or 30), int(eff.get("max") or row.get("chunk_max") or 90),
            bool(row.get("can_split", True)), row.get("focus", "high"), mandatory)
    raw = {"week_start": ws.isoformat(), "now": _iso(win["now"]), "fixed": fixed, "deadlines": deadlines}
    return raw, meta


def _floor5(x: int) -> int:
    return x // STEP * STEP


def _ceil5(x: int) -> int:
    return -(-x // STEP) * STEP


def apply_ui_overrides(inst, meta: UiMeta):
    """normalizer chỉ biết buffer có/không và chunk theo focus; UI cho nhập buffer 0-60 và chunk min/max riêng."""
    tasks = []
    for t in inst.tasks:
        m = meta.deadlines.get(t.id)
        if m is None:
            tasks.append(t)
            continue
        mx = max(STEP, _floor5(min(m.chunk_max, t.remaining)))
        mn = min(mx, max(STEP, _ceil5(min(m.chunk_min, t.remaining))))
        tasks.append(replace(t, buffer=m.buffer_min, min_chunk=mn, max_chunk=mx))
    return replace(inst, tasks=tasks)
