from __future__ import annotations

import argparse
import sys
from itertools import zip_longest
from pathlib import Path

from models import MINUTES_PER_DAY, Config, FixedTask, SolveResult, Task
from parseInput import parse_input
from parseOutput import parse_output


def print_table(headers, rows, *, compact=False):
    rows = [[str(value) for value in row] for row in rows]
    widths = [
        max(len(header), max((len(row[i]) for row in rows), default=0))
        for i, header in enumerate(headers)
    ]
    padding = "" if compact else " "
    border = "+" + "+".join("-" * (width + 2 * len(padding)) for width in widths) + "+"

    def line(row):
        return "|" + "|".join(
            f"{padding}{value.ljust(width)}{padding}" for value, width in zip(row, widths)
        ) + "|"

    print(border)
    print(line(headers))
    print(border)
    for row in rows:
        print(line(row))
    print(border)


def clock_time(minutes: int) -> str:
    hour, minute = divmod(minutes, 60)
    return f"{hour:02d}:{minute:02d}"


def print_free_time(result: SolveResult, tasks: list[Task],
                    fixed: list[FixedTask], cfg: Config) -> None:
    busy = [(item.start, item.end) for item in fixed]
    for task in tasks:
        chunks = result.chunks.get(task.id, [])
        if not chunks:
            continue
        break_slots = -cfg.to_slot(-task.break_minutes)
        buffer_slots = cfg.to_slot(task.buffer_minutes)
        last_end = max(end for _, end in chunks)
        for start, end in chunks:
            padding = max(break_slots, buffer_slots) if end == last_end else break_slots
            busy.append((cfg.to_minutes(start), cfg.to_minutes(end + padding)))
    busy.sort()

    columns = []
    for day in range(cfg.num_days):
        base = day * MINUTES_PER_DAY
        cursor = max(cfg.now, base + cfg.day_start)
        day_end = base + cfg.day_end
        gaps = []
        for start, end in busy:
            if cursor >= day_end or start >= day_end:
                break
            if end <= cursor:
                continue
            if start > cursor:
                gaps.append((cursor, start))
            cursor = max(cursor, end)
        if cursor < day_end:
            gaps.append((cursor, day_end))
        columns.append([
            f"{clock_time(start - base)}-{clock_time(end - base)}"
            for start, end in gaps
        ] or ["—"])

    weekdays = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ nhật"]
    print("\nKHOẢNG TRỐNG TRONG GIỜ LÀM VIỆC")
    print_table(weekdays[:cfg.num_days], zip_longest(*columns, fillvalue=""), compact=True)


def print_result(result: SolveResult, tasks: list[Task],
                 fixed: list[FixedTask], cfg: Config) -> None:
    print(f"Trang thai: {result.status}")
    print(f"Thoi gian giai: {result.solve_time:.3f} giay")
    weights = {
        name: weight for name, weight in (cfg.objective or {}).items()
        if weight > 0
    } or {"max_priority": 1}
    print("Muc tieu: " + ", ".join(
        f"{name}={weight}" for name, weight in weights.items()
    ))

    if result.status not in ("OPTIMAL", "FEASIBLE"):
        messages = {
            "INFEASIBLE": "Khong co lich thoa man cac rang buoc.",
            "UNKNOWN": "Chua tim duoc nghiem hoac ket luan.",
            "MODEL_INVALID": "Mo hinh khong hop le.",
        }
        print(messages.get(result.status, "Khong co lich de hien thi."))
        return

    print(f"Task duoc xep: {len(result.chunks)}/{len(tasks)}")
    print("Ngay hien thi tu 1; ngay trong input bat dau tu 0.")

    by_id = {t.id: t for t in tasks}
    entries = []
    for task_id, pieces in result.chunks.items():
        task = by_id[task_id]
        for index, (start, end) in enumerate(pieces, 1):
            day, slot_in_day = divmod(start, cfg.slots_per_day)
            start_minute = cfg.to_minutes(slot_in_day)
            end_minute = cfg.to_minutes(end - day * cfg.slots_per_day)
            entries.append((day, start_minute, end_minute, "Task",
                            str(task_id), task.name, f"{index}/{len(pieces)}"))
    for item in fixed:
        day, start = divmod(item.start, 1440)
        end = item.end - day * 1440
        entries.append((day, start, end, "Co dinh",
                        "-", item.name, "-"))

    print("\nLICH")
    rows = [
        [day + 1, kind, task_id, name, piece, clock_time(start),
         clock_time(end), end - start]
        for day, start, end, kind, task_id, name, piece in sorted(entries)
    ]
    print_table(
        ["Ngay", "Loai", "ID", "Cong viec", "Manh", "Bat dau", "Ket thuc", "Phut"],
        rows,
    )
    print_free_time(result, tasks, fixed, cfg)

    omitted = [t for t in tasks if t.id not in result.chunks]
    if omitted:
        print("\nTASK KHONG DUOC CHON")
        print_table(
            ["ID", "Cong viec", "Phut", "Priority"],
            [[t.id, t.name, t.duration, t.priority] for t in omitted],
        )



def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Xep lich tu file JSON.")
    parser.add_argument("input", help="Duong dan file JSON dau vao")
    parser.add_argument(
        "-o", "--output", help="File JSON ket qua; mac dinh: <input>_result.json"
    )
    args = parser.parse_args()
    input_path = Path(args.input)
    output_path = (
        Path(args.output) if args.output
        else input_path.with_name(input_path.stem + "_result.json")
    )
    if input_path.resolve() == output_path.resolve():
        parser.error("File output phai khac file input.")

    from solve import solve

    tasks, cfg, fixed = parse_input(str(input_path))
    result = solve(tasks, fixed, cfg)
    output_path.write_text(parse_output(result, cfg, tasks) + "\n", encoding="utf-8")
    print_result(result, tasks, fixed, cfg)
    print(f"\nJSON ket qua: {output_path}")
    return 0 if result.status in ("OPTIMAL", "FEASIBLE") else 1


if __name__ == "__main__":
    raise SystemExit(main())
