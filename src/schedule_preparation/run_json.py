"""Chạy RIÊNG Validate / Chia phút từ một file .json.

    python -m schedule_preparation.run_json examples/gui_snapshot.json
    python -m schedule_preparation.run_json examples/gui_snapshot.json --only validate
    python -m schedule_preparation.run_json examples/gui_snapshot.json --only split -o out.json
    python -m schedule_preparation.run_json examples/raw_week.json --answers '{"0": "keep"}'

Input tự nhận dạng:
  - snapshot của GUI (có "schema_version": 2)  -> ui_adapter.snapshot_to_raw + áp buffer/chunk riêng của GUI
  - raw dict của normalizer (week_start/now/fixed/deadlines)

Không gọi conflict resolver: khi xung đột chỉ trả về status CONFLICT / CANNOT_SPLIT kèm mô tả.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

from .m_split import show, split_minutes
from .m_validate import validate_week
from .ui_adapter import apply_ui_overrides, snapshot_to_raw


def load_input(src: Any) -> Tuple[dict, Optional[Callable]]:
    """đường dẫn | chuỗi JSON | dict  ->  (raw, tweak). tweak=None nếu input đã là raw."""
    if isinstance(src, (str, Path)):
        text = str(src)
        src = json.loads(text) if text.lstrip().startswith("{") else json.loads(Path(text).read_text(encoding="utf-8-sig"))
    if isinstance(src, dict) and src.get("schema_version") is not None:
        raw, meta = snapshot_to_raw(src)
        return raw, (lambda inst: apply_ui_overrides(inst, meta))
    return src, None


def validate_json(src: Any, answers: Optional[dict] = None) -> dict:
    raw, tweak = load_input(src)
    return validate_week(raw, answers, tweak)


def split_json(src: Any, answers: Optional[dict] = None) -> dict:
    raw, tweak = load_input(src)
    return split_minutes(raw, answers, tweak)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="schedule_preparation.run_json", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--only", choices=["validate", "split", "both"], default="both")
    ap.add_argument("--answers", default=None, help='JSON, ví dụ {"0":"keep"}')
    ap.add_argument("-o", "--output", default=None, help="ghi JSON ra file thay vì in ra màn hình")
    ap.add_argument("--text", action="store_true", help="in bảng chia phút dạng chữ thay vì JSON")
    a = ap.parse_args(argv)
    answers = {int(k) if str(k).isdigit() else k: v for k, v in json.loads(a.answers).items()} if a.answers else None
    out = {}
    if a.only in ("validate", "both"):
        out["validate"] = validate_json(a.input, answers)
    if a.only in ("split", "both"):
        out["split"] = split_json(a.input, answers)
    if a.text and "split" in out:
        print(show(out["split"]))
        return 0
    text = json.dumps(out if a.only == "both" else next(iter(out.values())), ensure_ascii=False, indent=2)
    if a.output:
        Path(a.output).write_text(text, encoding="utf-8")
        print(f"đã ghi {a.output}")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
