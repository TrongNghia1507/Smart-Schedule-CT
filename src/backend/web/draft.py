from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field

from backend.clock import now_vn_naive
from conflict_resolver.calendar_view import contrasting_text
from schedule_input.application.calendar_edit import moved_task
from schedule_input.application.import_export import ImportExportService
from schedule_input.application.mapper import TaskFactory
from schedule_input.application.parsers import DateTimeParser
from schedule_input.application.preview import PreviewService
from schedule_input.application.services import TaskInputService
from schedule_input.domain.models import FixedTask, PlanningWindow, ScheduleInput, SleepWindow, TimeRange
from schedule_input.infrastructure.io import CsvXlsxGateway, SampleDataProvider
from schedule_input.infrastructure.repositories import InMemoryRepository, JsonFileRepository, draft_payload

from .auth import Session, planner
from .errors import WebError, not_found, stale
from .locale import localize
from .storage import database, encode

router = APIRouter(prefix="/draft", tags=["draft"])
MAX_CSV_BYTES = 2 * 1024 * 1024
Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]


@dataclass
class Draft:
    revision: int
    service: TaskInputService
    colors: dict[str, str]
    previous: dict | None
    notes: list[str]

    def saved_data(self):
        return {"payload": draft_payload(self.service.data), "colors": dict(self.colors), "notes": list(self.notes)}


def monday(today: date | None = None):
    today = today or now_vn_naive().date()
    return today - timedelta(days=today.weekday())


def window(week_start: date, sleep: SleepWindow | None = None):
    if week_start.weekday() != 0:
        raise ValueError("Hãy chọn ngày Thứ Hai.")
    return PlanningWindow(week_start, datetime.combine(week_start, time.min), sleep or SleepWindow())


def load_payload(payload):
    default = ScheduleInput(window(monday()))
    if payload is None:
        return default
    parser = JsonFileRepository("unused.json")
    data, _, _ = parser.load_payload(payload, default)
    if parser.blocked:
        raise RuntimeError("Bản nháp SQLite không hợp lệ.")
    data.window = window(data.window.week_start, data.window.sleep)
    return data


def load_draft(conn, user_id: int) -> Draft:
    row = conn.execute("SELECT * FROM web_drafts WHERE user_id=?", (user_id,)).fetchone()
    data = load_payload(json.loads(row["payload"]) if row else None)
    service = TaskInputService(data, InMemoryRepository(), data.window.now)
    if not row:
        return Draft(0, service, {}, None, [])
    return Draft(row["revision"], service, json.loads(row["colors"]), previous_state(conn, user_id),
                 json.loads(row["notes"]))


def previous_state(conn, user_id: int):
    row = conn.execute(
        "SELECT state FROM web_draft_undo WHERE user_id=? ORDER BY revision DESC LIMIT 1", (user_id,)
    ).fetchone()
    return json.loads(row["state"]) if row else None


def check_revision(draft: Draft, expected: int):
    if draft.revision != expected:
        raise stale()


def save_draft(conn, user_id: int, draft: Draft, previous: dict | None):
    if previous is not None:
        conn.execute("INSERT INTO web_draft_undo VALUES (?,?,?)", (user_id, draft.revision, encode(previous)))
        draft.previous = previous
    draft.revision += 1
    saved = draft.saved_data()
    conn.execute(
        """INSERT INTO web_drafts(user_id, revision, payload, colors, notes)
           VALUES (?,?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET revision=excluded.revision, payload=excluded.payload,
           colors=excluded.colors, notes=excluded.notes""",
        (user_id, draft.revision, encode(saved["payload"]), encode(draft.colors), encode(draft.notes)),
    )


def report_data(report):
    return [{**asdict(issue), "message": localize(issue.message)} for issue in report.issues]


def require_valid(report):
    if report.has_errors():
        raise WebError(422, "DRAFT_INVALID", "Hãy kiểm tra các trường được đánh dấu.", report_data(report))


def describe(draft: Draft):
    data = draft.service.data
    return {
        "revision": draft.revision,
        "settings": draft.saved_data()["payload"]["settings"],
        "fixed_tasks": [TaskFactory.to_row_view(task) for task in data.fixed_tasks],
        "deadline_tasks": [TaskFactory.to_row_view(task) for task in data.deadline_tasks],
        "colors": draft.colors,
        "issues": report_data(draft.service.review()),
        "can_undo": draft.previous is not None,
        "notes": [localize(note) for note in draft.notes],
    }


class ChangeBase(BaseModel):
    expected_revision: int = Field(ge=0)


class SettingsChange(ChangeBase):
    action: Literal["settings"]
    week_start: date
    sleep_start: str
    sleep_end: str


class TaskChange(ChangeBase):
    action: Literal["task"]
    task_id: str | None = None
    fixed: bool
    fields: dict[str, str | int | bool | None]
    color: Color | None = None


class DeleteChange(ChangeBase):
    action: Literal["delete"]
    task_id: str


class MoveChange(ChangeBase):
    action: Literal["move"]
    task_id: str
    old_start: str
    new_start: str
    current_week: bool = False


class ReplaceChange(ChangeBase):
    action: Literal["clear", "sample", "undo"]


Change = Annotated[SettingsChange | TaskChange | DeleteChange | MoveChange | ReplaceChange,
                   Field(discriminator="action")]


@router.get("")
def read(current: Session = Depends(planner)):
    with database() as conn:
        return describe(load_draft(conn, current.user.id))


@router.post("/changes")
def change(command: Change, current: Session = Depends(planner)):
    with database(write=True) as conn:
        draft = load_draft(conn, current.user.id)
        check_revision(draft, command.expected_revision)
        previous = draft.saved_data()
        service = draft.service
        if isinstance(command, SettingsChange):
            sleep = TimeRange(DateTimeParser.time(command.sleep_start), DateTimeParser.time(command.sleep_end, True))
            service.data.window = window(command.week_start, SleepWindow(sleep.start, sleep.end))
        elif isinstance(command, TaskChange):
            fields = {**command.fields, "id": command.task_id}
            before = set(service.data._tasks)
            if command.task_id is not None:
                task = service.data._tasks.get(command.task_id)
                if task is None or isinstance(task, FixedTask) != command.fixed:
                    raise not_found()
                require_valid(service.update(command.task_id, fields))
            else:
                require_valid(service.submit(fields, command.fixed))
            if command.fixed and "color" in command.model_fields_set:
                task_id = command.task_id or next(iter(set(service.data._tasks) - before))
                draft.colors.pop(task_id, None)
                if command.color is not None:
                    draft.colors[task_id] = command.color
        elif isinstance(command, DeleteChange):
            if command.task_id not in service.data._tasks:
                raise not_found()
            service.remove(command.task_id)
            draft.colors.pop(command.task_id, None)
        elif isinstance(command, MoveChange):
            task = service.data._tasks.get(command.task_id)
            if not isinstance(task, FixedTask):
                raise not_found()
            displayed = PreviewService().build(preview_input(service.data, now_vn_naive(), command.current_week)).events
            if not any(event.task_id == task.id and event.start == datetime.fromisoformat(command.old_start)
                       for event in displayed):
                raise stale()
            moved = moved_task(task, command.old_start, command.new_start)
            require_valid(service.update(task.id, TaskFactory.to_row_view(moved)))
        elif command.action == "undo":
            if draft.previous is None:
                raise WebError(409, "NO_UNDO", "Không có thay đổi để hoàn tác.")
            service.data = load_payload(draft.previous["payload"])
            draft.colors = draft.previous["colors"]
            draft.notes = draft.previous["notes"]
            conn.execute(
                "DELETE FROM web_draft_undo WHERE user_id=? AND revision="
                "(SELECT MAX(revision) FROM web_draft_undo WHERE user_id=?)", (current.user.id, current.user.id),
            )
            draft.previous = previous_state(conn, current.user.id)
            previous = None
        elif command.action == "sample":
            service.data = SampleDataProvider().demo(now_vn_naive())
            draft.colors = {}
        else:
            service.data = ScheduleInput(service.data.window)
            draft.colors = {}
        service.now_override = datetime.combine(service.data.window.week_start, time.min)
        service.data.window = replace(service.data.window, now=service.now_override)
        save_draft(conn, current.user.id, draft, previous)
        return describe(draft)


def preview_input(source: ScheduleInput, today: datetime, current_week: bool):
    data = deepcopy(source)
    data.window = replace(data.window, week_start=monday(today.date()) if current_week else data.window.week_start,
                          now=today)
    return data


@router.get("/preview")
def preview(current_week: bool = False, current: Session = Depends(planner)):
    with database() as conn:
        draft = load_draft(conn, current.user.id)
    today = now_vn_naive()
    data = preview_input(draft.service.data, today, current_week)
    model = PreviewService().build(data)
    issues = draft.service.review()
    overlaps = {issue.task_id for issue in issues.issues if issue.code == "F04"}
    events = []
    for event in model.events:
        color = draft.colors.get(event.task_id, "#187463")
        start, end = event.start.isoformat(), event.end.isoformat()
        events.append({
            "id": f"{event.task_id}@{start}#{event.segment_index}", "title": event.title,
            "start": start, "end": end, "editable": True,
            "backgroundColor": color, "borderColor": "#e4a83a" if event.task_id in overlaps else color,
            "textColor": contrasting_text(color),
            "extendedProps": {"task_id": event.task_id, "kind": "fixed"},
        })
    for task in data.fixed_tasks:
        for start, end in task.occurrences(data.window.week_start):
            for minutes, begin, finish, kind in (
                (task.prep_min, start - timedelta(minutes=task.prep_min), start, "prep"),
                (task.after_min, end, end + timedelta(minutes=task.after_min), "after"),
            ):
                if minutes:
                    events.append({
                        "id": f"{kind}-{task.id}-{start.isoformat()}", "title": task.name,
                        "start": begin.isoformat(), "end": finish.isoformat(), "editable": False,
                        "classNames": ["reserve-band"], "extendedProps": {"kind": kind, "task_id": task.id},
                    })
    for i, band in enumerate(model.bands):
        events.append({"id": f"sleep-{i}", "start": band.start, "end": band.end, "display": "background",
                       "editable": False, "classNames": ["sleep-band"]})
    return {"revision": draft.revision, "week_start": data.window.week_start, "events": events,
            "free_minutes": model.free_minutes, "now": today.isoformat(), "issues": report_data(issues)}


async def read_csv(request: Request) -> bytes:
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_CSV_BYTES:
            raise WebError(413, "CSV_TOO_LARGE", "CSV tối đa 2 MB.")
    return bytes(content)


def import_preview(draft: Draft, content: bytes):
    candidate, results, unknown = ImportExportService().preview_mixed(draft.service, content)
    return candidate, {"unknown": unknown, "rows": [{"line": line, "issues": report_data(report)}
                                                    for line, report in results],
                       "valid": sum(not report.has_errors() for _, report in results)}


def export_file(content: bytes | str, name: str, media_type: str):
    return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/imports/preview")
def preview_import(content: bytes = Depends(read_csv), current: Session = Depends(planner)):
    with database() as conn:
        draft = load_draft(conn, current.user.id)
    _, result = import_preview(draft, content)
    return {**result, "revision": draft.revision}


@router.post("/imports")
def import_csv(expected_revision: int = Query(ge=0), content: bytes = Depends(read_csv),
               current: Session = Depends(planner)):
    with database(write=True) as conn:
        draft = load_draft(conn, current.user.id)
        check_revision(draft, expected_revision)
        candidate, result = import_preview(draft, content)
        if result["valid"] == 0:
            raise WebError(422, "CSV_NO_VALID_ROWS", "CSV không có dòng hợp lệ.")
        previous = draft.saved_data()
        draft.service.data = candidate
        save_draft(conn, current.user.id, draft, previous)
        return describe(draft)


@router.get("/export")
def export_csv(current: Session = Depends(planner)):
    with database() as conn:
        draft = load_draft(conn, current.user.id)
    return export_file(CsvXlsxGateway().write_mixed_rows(draft.service.data), "tasks.csv", "text/csv")


@router.get("/example")
def example_csv(lang: Literal["vi", "en"] = "vi", current: Session = Depends(planner)):
    with database() as conn:
        draft = load_draft(conn, current.user.id)
    return export_file(CsvXlsxGateway().example(draft.service.data.window, lang), "tasks_example.csv", "text/csv")


@router.get("/snapshot")
def export_snapshot(current: Session = Depends(planner)):
    with database() as conn:
        draft = load_draft(conn, current.user.id)
    require_valid(draft.service.review())
    return export_file(draft.service.confirm().to_json(), "input_snapshot.json", "application/json")
