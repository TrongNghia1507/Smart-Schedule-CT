"""Import Streamlit's per-user JSON files into the React application's SQLite database."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

from schedule_input.domain.models import ScheduleInput
from schedule_input.infrastructure.repositories import JsonFileRepository, draft_payload
from scheduling_algorithm.core_algorithm.history import load_schedule_history
from user_portal.db import connect

from .draft import monday, window
from .history import history_events
from .storage import db_path, encode, initialize

COLOR = re.compile(r"#[a-fA-F0-9]{6}")


def source_connection(source):
    return closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True))


def users_in(conn):
    return {row[0]: tuple(row[1:]) for row in conn.execute("SELECT id,username,role,created_at FROM users ORDER BY id")}


def legacy_draft(folder, problems):
    path = folder / "schedule_input_draft.json"
    alternatives = sorted(file.name for file in folder.glob("draft_*.json"))
    if alternatives:
        problems.append(f"{folder.name}: chỉ nhập nháp chính; kiểm tra thủ công {', '.join(alternatives)}")
    colors = {}
    color_path = folder / "calendar_colors.json"
    if color_path.exists():
        try:
            raw = json.loads(color_path.read_text(encoding="utf-8-sig"))
            colors = {key: value for key, value in raw.items() if isinstance(value, str) and COLOR.fullmatch(value)}
            if len(colors) != len(raw):
                problems.append(f"{folder.name}: có màu không hợp lệ trong {color_path.name}")
        except (OSError, ValueError, AttributeError):
            problems.append(f"{folder.name}: không đọc được {color_path.name}")
    if not path.exists() and not colors:
        return None
    parser = JsonFileRepository(path)
    data, _, notes = parser.load(ScheduleInput(window(monday())), preserve_source=True)
    for note in notes:
        if note.startswith(("Không đọc được bản ghi", "ID trùng")) or parser.blocked:
            problems.append(f"{folder.name}: {note}")
    if parser.blocked:
        return None
    return draft_payload(data), colors, notes


def legacy_history(folder, problems):
    try:
        candidates = load_schedule_history(folder / "schedule_history.json")
    except (OSError, ValueError) as exc:
        problems.append(f"{folder.name}: {exc}")
        return None
    records = []
    seen = set()
    for index, record in enumerate(reversed(candidates), start=1):
        try:
            if not isinstance(record["id"], str) or not record["id"] or record["id"] in seen:
                raise ValueError("ID lịch thiếu hoặc trùng")
            date.fromisoformat(record["week_start"])
            if record.get("version") is not None and type(record["version"]) is not int:
                raise ValueError("Phiên bản lịch không hợp lệ")
            history_events(record, "vi")
            encode(record)
        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            problems.append(f"{folder.name}: bỏ qua lịch dòng {index}: {exc}")
            continue
        seen.add(record["id"])
        records.append(record)
    return records


def migrate(source_db: Path, source_dir: Path, destination: Path, *, apply=False):
    if not source_db.is_file():
        raise FileNotFoundError(source_db)
    if not source_dir.is_dir():
        raise FileNotFoundError(source_dir)
    if source_db.resolve() == destination.resolve():
        raise ValueError("Chọn một SQLite đích riêng để giữ nguyên bản Streamlit.")
    problems = []
    with source_connection(source_db) as source:
        users = users_in(source)
        counts = {
            table: source.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("users", "login_events", "finalized_schedules", "ratings")
        }
        imports = []
        for user_id, (_, role, _) in users.items():
            if role != "user":
                continue
            folder = source_dir / "users" / f"u{user_id}"
            imports.append((user_id, legacy_draft(folder, problems), legacy_history(folder, problems)))
        known_dirs = {f"u{user_id}" for user_id in users}
        for folder in (source_dir / "users").glob("u*"):
            if folder.is_dir() and folder.name not in known_dirs:
                problems.append(f"{folder.name}: không có tài khoản tương ứng trong SQLite nguồn")
        if apply and not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation prevents accidentally overwriting an existing portal.
            destination.touch(exist_ok=False)
            try:
                with closing(sqlite3.connect(destination)) as target:
                    source.backup(target)
            except (OSError, sqlite3.Error):
                destination.unlink(missing_ok=True)
                raise
    summary = {
        "source": counts, "draft_candidates": sum(draft is not None for _, draft, _ in imports),
        "history_candidates": sum(len(history or []) for _, _, history in imports),
        "drafts_imported": 0, "history_imported": 0, "issues": problems,
    }
    if not apply:
        return summary
    with connect(destination) as conn:
        identities = users_in(conn)
        if any(identities.get(user_id) != identity for user_id, identity in users.items()):
            raise ValueError("SQLite đích có tài khoản khác nguồn. Hãy dùng đường dẫn đích mới.")
    initialize(destination)
    with connect(destination) as conn:
        conn.execute("BEGIN IMMEDIATE")
        for user_id, draft, history in imports:
            if draft is not None:
                payload, colors, notes = draft
                inserted = conn.execute(
                    """INSERT OR IGNORE INTO web_drafts(user_id,revision,payload,colors,notes) VALUES (?,1,?,?,?)""",
                    (user_id, encode(payload), encode(colors), encode(notes)),
                )
                summary["drafts_imported"] += inserted.rowcount
            for record in history or ():
                marker = conn.execute("INSERT OR IGNORE INTO web_legacy_history_imports VALUES (?,?)",
                                      (user_id, record["id"]))
                if not marker.rowcount:
                    continue
                inserted = conn.execute("INSERT OR IGNORE INTO web_history VALUES (?,?,?,?)",
                                        (user_id, record["id"], record["week_start"], encode(record)))
                summary["history_imported"] += inserted.rowcount
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--source-db", type=Path)
    parser.add_argument("--destination", type=Path, default=db_path())
    parser.add_argument("--apply", action="store_true", help="Ghi vào SQLite đích. Mặc định chỉ kiểm tra.")
    args = parser.parse_args()
    result = migrate(args.source_db or args.source_dir / "portal.db", args.source_dir,
                     args.destination, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
