from __future__ import annotations

import argparse
from pathlib import Path

from models import Config, FixedTask, SolveResult, Task
from parseInput import parse_input
from parseOutput import parse_output


def print_table(headers, rows):
    rows = [[str(value) for value in row] for row in rows]
    widths = [
        max(len(header), max((len(row[i]) for row in rows), default=0))
        for i, header in enumerate(headers)
    ]
    border = "+-" + "-+-".join("-" * width for width in widths) + "-+"

    def line(row):
        return "| " + " | ".join(
            value.ljust(width) for value, width in zip(row, widths)
        ) + " |"

    print(border)
    print(line(headers))
    print(border)
    for row in rows:
        print(line(row))
    print(border)


def clock_time(minutes: int) -> str:
    hour, minute = divmod(minutes, 60)
    return f"{hour:02d}:{minute:02d}"


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
        entries.append((item.day, item.start, item.end, "Co dinh",
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

    omitted = [t for t in tasks if t.id not in result.chunks]
    if omitted:
        print("\nTASK KHONG DUOC CHON")
        print_table(
            ["ID", "Cong viec", "Phut", "Priority"],
            [[t.id, t.name, t.duration, t.priority] for t in omitted],
        )



def main() -> int:
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
