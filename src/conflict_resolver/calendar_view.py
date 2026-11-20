"""Project a solved schedule into the weekly calendar and option previews."""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape

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
    # Pick the more legible foreground using relative luminance in linear sRGB.
    normalized = [value / 255 for value in shaded]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
              for value in normalized]
    luminance = sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    return "#" + "".join(f"{value:02x}" for value in shaded), "#000000" if luminance >= 0.179 else "#ffffff"


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
        return block.title, color, "#101820"
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


PREVIEW_CSS = """
<style>
.option-preview {position:relative}
.option-preview summary {cursor:pointer; color:var(--app-blue); font-weight:650; padding:.4rem 0}
.option-preview summary small {font-weight:400; color:var(--app-muted); margin-left:.5rem}
.option-preview-panel {display:none; position:absolute; top:100%; left:0; z-index:30;
  width:min(740px,100%); padding:.65rem; border:1px solid var(--app-border); border-radius:12px;
  background:var(--app-surface); color:var(--app-text); box-shadow:0 8px 28px #10182035}
.option-preview:hover > .option-preview-panel,
.option-preview:has(summary:focus-visible) > .option-preview-panel,
.option-preview:has(details[open]) > .option-preview-panel {display:block}
.option-preview-title {font-size:.8rem; font-weight:650; margin:0 0 .4rem}
.mini-calendar {max-height:290px; overflow:auto; border:1px solid var(--app-border); border-radius:6px}
.mini-days,.mini-grid {display:grid; grid-template-columns:2.65rem repeat(7,minmax(62px,1fr))}
.mini-days {position:sticky; top:0; z-index:5; background:var(--app-soft); text-align:center; font-size:.72rem}
.mini-days span {padding:.25rem .1rem; border-right:1px solid var(--app-border)}
.mini-time,.mini-day {position:relative; border-right:1px solid var(--app-border);
  background:repeating-linear-gradient(to bottom,var(--app-border) 0 1px,transparent 1px 26px)}
.mini-hour {position:absolute; right:.3rem; color:var(--app-muted); font-size:.64rem; line-height:1.2}
.mini-block {position:absolute; z-index:2; left:2px; right:2px; border-radius:4px;
  padding:0 3px; font-size:.64rem; line-height:1.25; overflow:hidden; overflow-wrap:anywhere}
.mini-block.sleep {z-index:0; left:0; right:0; border-radius:0;
  background:repeating-linear-gradient(135deg,var(--app-stripe) 0 3px,transparent 3px 6px)!important}
.mini-block.reserve {z-index:1}
</style>
"""


def option_preview_html(heading, week_start, blocks, styles, fixed_colors, lang):
    """Build the hover card without a server round trip or a schedule mutation."""
    segments = [[] for _ in range(7)]
    visible_starts, visible_ends = [], []
    for block in blocks:
        for day in range(max(0, block.start // DAY), min(7, (block.end + DAY - 1) // DAY)):
            start = max(0, block.start - day * DAY)
            end = min(DAY, block.end - day * DAY)
            segments[day].append((start, end, block))
            if block.kind != "sleep":
                visible_starts.append(start)
                visible_ends.append(end)
    first_hour = min(visible_starts, default=360) // 60
    last_hour = (max(visible_ends, default=1320) + 59) // 60
    height = (last_hour - first_hour) * 26
    weekdays = ("T2", "T3", "T4", "T5", "T6", "T7", "CN") if lang == "vi" else (
        "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"
    )
    headers = "".join(f"<span>{label} {(week_start + timedelta(days=day)):%d/%m}</span>"
                      for day, label in enumerate(weekdays))
    hours = "".join(f'<span class="mini-hour" style="top:{(hour - first_hour) * 26}px">{hour:02}:00</span>'
                    for hour in range(first_hour, last_hour, 2))
    columns = []
    for day_blocks in segments:
        pieces = []
        for start, end, block in day_blocks:
            top = max(0, (start - first_hour * 60) * 26 / 60)
            bottom = min(height, (end - first_hour * 60) * 26 / 60)
            if bottom <= top:
                continue
            title, background, foreground = block_appearance(block, styles, fixed_colors)
            title = escape(title)
            tooltip = f"{start // 60:02}:{start % 60:02} – {end // 60:02}:{end % 60:02} · {title}"
            label = "" if block.kind in ("sleep", "reserve") else title
            pieces.append(
                f'<div class="mini-block {block.kind}" title="{tooltip}" '
                f'style="top:{top:.1f}px;height:{bottom - top:.1f}px;background:{background};color:{foreground}">'
                f'{label}</div>'
            )
        columns.append(f'<div class="mini-day">{"".join(pieces)}</div>')
    title = "Lịch theo phương án" if lang == "vi" else "Schedule for this option"
    hint = "Xem thử lịch" if lang == "vi" else "Preview schedule"
    return (
        f'<div class="option-preview"><details><summary>{escape(heading)} <small>{hint}</small>'
        '</summary></details>'
        f'<section class="option-preview-panel" aria-label="{title}"><div class="option-preview-title">{title}</div>'
        f'<div class="mini-calendar" tabindex="0"><div class="mini-days"><span></span>{headers}</div>'
        f'<div class="mini-grid" style="height:{height}px"><div class="mini-time">{hours}</div>'
        f'{"".join(columns)}</div></div></section></div>'
    )
