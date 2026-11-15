"""Điều phối: kiểm tra khả năng hoàn thành -> nếu thiếu thời gian thì gọi conflict_resolver."""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from conflict_resolver.models import ConflictReport

from .capacity import Checkpoint, capacity_checkpoints
from .model import WeekModel, build_week_model, describe_minute
from .policy import ResolutionPolicy

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Kết nối tới resolver: trong cùng tiến trình hoặc qua FastAPI (/conflicts/analyze)
# ---------------------------------------------------------------------------
class LocalResolverClient:
    def __init__(self, scheduler=None, settings=None):
        self.scheduler = scheduler
        self.settings = settings

    async def analyze(self, context):
        from conflict_resolver.ai.advisor import get_settings
        from conflict_resolver.resolver import resolve
        from conflict_resolver.scheduler import ReferenceScheduler

        scheduler = self.scheduler or ReferenceScheduler()
        return await resolve(context, scheduler, self.settings or get_settings())


class HttpResolverClient:
    def __init__(self, base_url, timeout=60.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def analyze(self, context):
        import httpx

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/conflicts/analyze",
                json=context.model_dump(mode="json"),
            )
            response.raise_for_status()
            return ConflictReport.model_validate(response.json())


# ---------------------------------------------------------------------------
# Kết quả
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Finding:
    kind: str                 # CAPACITY | UNSCHEDULABLE
    deadline: int | None
    demand: int
    free: int
    deficit: int
    target_id: str | None
    task_ids: tuple
    message: str


@dataclass
class FeasibilityReport:
    status: str                                   # OK | CONFLICT | NOT_CHECKED
    model: WeekModel | None = None
    checkpoints: list = field(default_factory=list)
    findings: list = field(default_factory=list)
    resolved: Finding | None = None               # mốc đã gọi resolver
    resolution: ConflictReport | None = None
    resolver_error: str | None = None
    notes: list = field(default_factory=list)

    @property
    def blocking(self):
        return self.status == "CONFLICT"


def _capacity_message(model, cp):
    names = ", ".join(
        model.origins[i].name for i in cp.task_ids if i in model.origins
    )
    return (
        f"Đến {describe_minute(cp.deadline)}: cần {cp.demand} phút "
        f"(gồm nghỉ đệm) cho {len(cp.task_ids)} việc [{names}] nhưng chỉ có "
        f"{cp.free} phút trống, thiếu {cp.deficit} phút."
    )


async def check_feasibility(
    data, *, client=None, policy=None, schedule_version=0
) -> FeasibilityReport:
    policy = policy or ResolutionPolicy()
    client = client or LocalResolverClient()

    model = build_week_model(data, policy)
    notes = list(model.notes)
    notes += [f"“{s.name}”: {s.reason}" for s in model.skipped if s.code == "AFTER_WEEK"]

    if model.reason:
        return FeasibilityReport("NOT_CHECKED", model=model, notes=[model.reason, *notes])

    findings = [
        Finding(
            "UNSCHEDULABLE", None, 0, 0, 0, s.task_id, (s.task_id,),
            f"“{s.name}”: {s.reason}",
        )
        for s in model.skipped if s.code == "EMPTY_WINDOW"
    ]

    if not model.tasks:
        status = "CONFLICT" if findings else "OK"
        return FeasibilityReport(status, model=model, findings=findings, notes=notes)

    checkpoints = capacity_checkpoints(model)
    solvable = [
        Finding(
            "CAPACITY", cp.deadline, cp.demand, cp.free, cp.deficit,
            cp.target_id, cp.task_ids, _capacity_message(model, cp),
        )
        for cp in checkpoints if cp.conflict
    ]

    findings = findings + solvable
    report = FeasibilityReport(
        "CONFLICT" if findings else "OK",
        model=model, checkpoints=checkpoints, findings=findings, notes=notes,
    )

    if not solvable:
        return report

    # Xử lý theo thứ tự thời gian: mốc sớm nhất trước, vì thiếu hụt ở mốc sau
    # đã gồm cả phần thiếu của mốc trước. Resolver chỉ nhìn "tiền tố" đến mốc đó.
    earliest = min(solvable, key=lambda f: f.deadline)
    report.resolved = earliest

    try:
        context = model.context_for(
            earliest.deadline, earliest.target_id,
            conflict_id=f"cf-{model.week_start:%Y%m%d}-{earliest.deadline}",
            version=schedule_version,
        )
        report.resolution = await client.analyze(context)
    except Exception as exc:  # UI không được sập vì resolver lỗi/quá giới hạn
        logger.exception("Resolver failed")
        report.resolver_error = f"{type(exc).__name__}: {exc}"
        return report

    if report.resolution.status == "NO_CONFLICT":
        report.notes.append(
            "Resolver xếp được tiền tố này dù phép cân đối báo thiếu; kiểm tra lại cấu hình."
        )
    return report


def check_feasibility_sync(data, **kwargs):
    """Dùng trong Streamlit (hàm đồng bộ)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(check_feasibility(data, **kwargs))

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(check_feasibility(data, **kwargs))).result()
