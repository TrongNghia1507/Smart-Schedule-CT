from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

WEEK = 7 * 24 * 60


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Interval(Model):
    start: int = Field(ge=0, lt=WEEK)
    end: int = Field(gt=0, le=WEEK)

    @model_validator(mode="after")
    def validate_interval(self):
        if self.start >= self.end:
            raise ValueError("start phải nhỏ hơn end")
        return self


class Task(Model):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)

    kind: Literal["hard", "soft", "asap"]
    importance: int = Field(ge=1, le=3)

    remaining_min: int = Field(gt=0, le=WEEK)
    earliest_start: int = Field(ge=0, lt=WEEK)
    deadline: int = Field(gt=0, le=WEEK)

    chunk_min: int = Field(gt=0, le=WEEK)
    chunk_max: int = Field(gt=0, le=WEEK)
    buffer_min: int = Field(default=0, ge=0, le=120)

    allow_compress: bool = False
    min_remaining_min: int = Field(default=1, gt=0, le=WEEK)

    allow_exclude: bool = False
    max_postpone_minutes: int = Field(default=0, ge=0, le=WEEK)

    @model_validator(mode="after")
    def validate_task(self):
        if self.earliest_start >= self.deadline:
            raise ValueError("earliest_start phải trước deadline")

        if self.chunk_min > self.chunk_max:
            raise ValueError("chunk_min không được lớn hơn chunk_max")

        if self.min_remaining_min > self.remaining_min:
            raise ValueError("min_remaining_min vượt remaining_min")

        return self


class FixedTask(Model):
    id: str
    name: str
    interval: Interval

    importance: int = Field(default=3, ge=1, le=3)
    can_shorten: bool = False
    min_duration: int = Field(default=1, ge=1, le=WEEK)

    @model_validator(mode="after")
    def validate_minimum(self):
        duration = self.interval.end - self.interval.start

        if self.min_duration > duration:
            raise ValueError("min_duration vượt thời lượng fixed task")

        return self


class Policy(Model):
    max_earlier_minutes: int = Field(default=0, ge=0, le=60)
    max_later_minutes: int = Field(default=0, ge=0, le=60)

    compression_step_minutes: int = Field(default=15, ge=1, le=60)


class ConflictContext(Model):
    conflict_id: str = Field(min_length=1, max_length=100)
    schedule_version: int = Field(ge=0)

    now_minute: int = Field(default=0, ge=0, lt=WEEK)
    target_task_id: str

    tasks: list[Task] = Field(min_length=1, max_length=100)
    fixed_tasks: list[FixedTask] = Field(default_factory=list, max_length=200)
    active_windows: list[Interval] = Field(min_length=1, max_length=21)

    policy: Policy = Field(default_factory=Policy)

    @model_validator(mode="after")
    def validate_context(self):
        ids = [task.id for task in self.tasks]
        ids += [task.id for task in self.fixed_tasks]

        if len(ids) != len(set(ids)):
            raise ValueError("ID của các task phải duy nhất")

        if self.target_task_id not in {task.id for task in self.tasks}:
            raise ValueError("Không tìm thấy target task")

        windows = sorted(self.active_windows, key=lambda item: item.start)

        for previous, current in zip(windows, windows[1:]):
            if previous.end > current.start:
                raise ValueError("active_windows không được chồng lấn")

        return self


class Chunk(Model):
    task_id: str
    start: int
    end: int
    buffer_end: int


class PlanResult(Model):
    status: Literal["FEASIBLE", "NOT_FOUND"]
    chunks: list[Chunk]
    unscheduled: dict[str, int]


class Option(Model):
    option_id: int
    type: str
    priority_rank: int = 0

    is_available: bool = False
    unavailable_reason: str | None = None

    factual_description: str = ""
    ai_description: str = ""

    action_payload: dict = Field(default_factory=dict)
    preview: list[Chunk] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ConflictReport(Model):
    conflict_id: str
    schedule_version: int

    status: Literal["CONFLICT", "NO_CONFLICT"]
    deficit_minutes: int

    ai_status: str
    verification_engine: str

    options: list[Option]