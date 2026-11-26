"""Project a solved schedule into the weekly calendar and option previews."""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

DAY = 1440
WEEK = 7 * DAY
DEADLINE_ACCENTS = (
    "#e39733", "#409c92", "#d14d78", "#a756b8", "#439363", "#499ed0",
    "#dc4f30", "#6389df", "#ba8b33", "#885c9e", "#2485a1", "#b86b57",
    "#7e8640", "#a74391", "#4774b1",
)
IMPORTANCE_BADGES = "①②③"
BLOCK_COLORS = {
    "fixed": ("#687c96", "#ffffff"),
    "reserve": ("#a3b2c5", "#152638"),
    "sleep": ("#e4eaf2", "#334459"),
}


@dataclass(frozen=True)
class Block:
    start: int
    end: int
    title: str
    kind: str
    ref_id: str = ""


def importance_colors(accent, level):
    """Keep the same hue while making priority 1 light and priority 3 dark."""
    channels = [int(accent[index:index + 2], 16) for index in (1, 3, 5)]
    target, amount = {1: (255, 0.58), 2: (0, 0), 3: (0, 0.38)}[level]
    shaded = [round(value + (target - value) * amount) for value in channels]
    background = "#" + "".join(f"{value:02x}" for value in shaded)
    return background, contrasting_text(background)


def contrasting_text(background):
    """Choose the text color with the higher WCAG contrast on an sRGB background."""
    normalized = [int(background[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
              for value in normalized]
    luminance = sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    return "#000000" if luminance >= 0.179 else "#ffffff"


def deadline_styles(tasks):
    # Use the original snapshot order so removing a task in an option cannot
    # change the colors of tasks that remain on the calendar.
    styles = {}
    for index, task in enumerate(tasks):
        level = task["importance"]
        accent = DEADLINE_ACCENTS[index % len(DEADLINE_ACCENTS)]
        background, foreground = importance_colors(accent, level)
        styles[task["id"]] = (IMPORTANCE_BADGES[level - 1], background, foreground)
    return styles


def schedule_blocks(entries, active_windows, lang="vi"):
    blocks = []
    totals = Counter(entry.ref_id for entry in entries if entry.kind == "TASK")
    indexes = Counter()
    sleep_title = "Giờ ngủ" if lang == "vi" else "Sleep"
    buffer_title = "Nghỉ ngơi" if lang == "vi" else "Break"

    for entry in sorted(entries, key=lambda item: (item.start, item.end, item.ref_id)):
        title = entry.name
        if entry.kind == "TASK":
            indexes[entry.ref_id] += 1
            if totals[entry.ref_id] > 1:
                title += f" ({indexes[entry.ref_id]}/{totals[entry.ref_id]})"
            blocks.append(Block(entry.start, entry.end, title, "deadline", entry.ref_id))
            if entry.buffer_end is not None and entry.buffer_end > entry.end:
                blocks.append(Block(entry.end, entry.buffer_end, f"{buffer_title} · {title}", "reserve"))
        elif entry.end > entry.start:
            kind = "reserve" if entry.ancillary else "fixed"
            blocks.append(Block(entry.start, entry.end, title, kind, entry.ref_id))

    previous_end = 0
    for window in sorted(active_windows, key=lambda item: item.start):
        if window.start > previous_end:
            blocks.append(Block(previous_end, window.start, sleep_title, "sleep"))
        previous_end = window.end
    if active_windows and previous_end < WEEK:
        blocks.append(Block(previous_end, WEEK, sleep_title, "sleep"))
    return blocks


def block_appearance(block, styles, fixed_colors):
    if block.kind == "deadline":
        badge, background, foreground = styles[block.ref_id]
        return f"{badge} {block.title}", background, foreground
    if block.kind == "fixed" and (color := fixed_colors.get(block.ref_id.split("@", 1)[0])):
        return block.title, color, contrasting_text(color)
    return block.title, *BLOCK_COLORS[block.kind]


def calendar_events(week_start, blocks, styles, fixed_colors):
    monday = datetime.combine(week_start, datetime.min.time())
    events = []
    for index, block in enumerate(blocks):
        title, background, foreground = block_appearance(block, styles, fixed_colors)
        classes = [f"{block.kind}-band"]
        if block.kind == "deadline" and block.end - block.start < 30:
            classes.append("short-event")
        event = {
            "id": f"planned-{index}",
            "title": title,
            "start": (monday + timedelta(minutes=block.start)).isoformat(),
            "end": (monday + timedelta(minutes=block.end)).isoformat(),
            "backgroundColor": background,
            "borderColor": background,
            "textColor": foreground,
            "editable": False,
            "classNames": classes,
        }
        if block.kind == "sleep":
            event["display"] = "background"
        events.append(event)
    return events
