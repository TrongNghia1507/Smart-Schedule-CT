from dataclasses import dataclass, field

from schedule_preparation.ui_adapter import (
    snapshot_to_raw,
    apply_ui_overrides,
)
from schedule_preparation.normalizer import normalize

from .models import (
    ConflictContext,
    Task,
    FixedTask,
    Interval,
    Policy,
)
from .scheduler import CoreScheduler
from .resolver import resolve

BASELINE_TIME_LIMIT = 10.0
ANALYZE_TIME_LIMIT = 5.0

engine = CoreScheduler(
    require_all=False,
    time_limit=BASELINE_TIME_LIMIT,
)
def context_from_snapshot(snapshot, policy=None):
    raw, meta = snapshot_to_raw(snapshot)

    instance, issues = normalize(raw)

    if instance is None or any(
        issue.level in {"ERROR", "ASK"}
        for issue in issues
    ):
        raise ValueError(
            "; ".join(
                issue.message
                for issue in issues
            )
        )

    instance = apply_ui_overrides(instance, meta)

    tasks = []

    for task in instance.tasks:
        task_meta = meta.deadlines[task.id]

        if task.deadline > 10080:
            raise ValueError(
                "Deadline ngoài tuần: cần chọn "
                "tuần kế tiếp trước khi xếp."
            )

        tasks.append(
            Task(
                id=task_meta.ui_id,
                name=task.name,
                mandatory=task_meta.mandatory,
                importance=task_meta.importance_ui,
                remaining_min=task.remaining,
                earliest_start=task.earliest_start,
                deadline=task.deadline,
                chunk_min=(
                    task.min_chunk
                    if task_meta.can_split
                    else task.remaining
                ),
                chunk_max=(
                    task.max_chunk
                    if task_meta.can_split
                    else task.remaining
                ),
                buffer_min=task.buffer,
                allow_compress=True,
                # Người dùng được quyền bỏ mọi task khi xử lý conflict;
                # option chỉ áp dụng khi họ chủ động chọn.
                allow_exclude=True,
                min_remaining_min=1,
            )
        )

    if not tasks:
        raise ValueError(
            "Cần ít nhất một task có hạn để xếp lịch."
        )

    fixed_tasks = [
        FixedTask(
            id=fixed.id,
            name=fixed.name,
            interval=Interval(
                start=fixed.start,
                end=fixed.end,
            ),
            can_shorten=(
                fixed.min_elastic is not None
            ),
            min_duration=(
                fixed.min_elastic
                or fixed.end - fixed.start
            ),
            can_remove=fixed.removable,
            # "F2@1.0", "F2@1.prep" -> cùng lần diễn ra "F2@1"
            group=fixed.id.split(".")[0],
            ancillary=fixed.type == "prep",
        )
        for fixed in instance.fixed
    ]

    active_windows = [
        Interval(
            start=(
                day * 1440
                + instance.cfg.day_start
            ),
            end=(
                day * 1440
                + instance.cfg.day_end
            ),
        )
        for day in range(7)
    ]

    return ConflictContext(
        conflict_id="week",
        schedule_version=0,
        now_minute=instance.now,
        target_task_id=tasks[0].id,
        tasks=tasks,
        fixed_tasks=fixed_tasks,
        active_windows=active_windows,
        policy=policy or Policy(),
    )

from .errors import SolverInconclusive
@dataclass
class PlanningSession:
    context: ConflictContext
    reports: dict = field(default_factory=dict)
    protected_ids: set = field(default_factory=set)
    cached_plan: object = None
    hint_chunks: list = field(default_factory=list)
    def plan(self):
        if self.cached_plan is None:
            engine = CoreScheduler(require_all=False, time_limit=BASELINE_TIME_LIMIT)

            result = engine.plan(
                self.context,
                required_ids=self.protected_ids,
                hint=self.hint_chunks,
            )

            if result.status == "UNKNOWN":
                raise SolverInconclusive(
                    "Solver hết thời gian trước khi tìm được lịch. "
                    "Hãy thử lại hoặc giảm số task."
                )

            self.cached_plan = result

        return self.cached_plan

    async def analyze(self, target_id, settings):
        baseline = self.plan()

        if target_id not in baseline.unscheduled:
            raise ValueError(
                "Task đã được xếp hoặc không tồn tại."
            )

        # Giữ mọi task đã xếp và thêm target đang xử lý.
        # Những task chưa xếp khác vẫn được lưu trong session.
        kept_ids = {
            chunk.task_id
            for chunk in baseline.chunks
        } | {target_id}

        scoped = self.context.model_copy(deep=True)

        scoped.tasks = [
            task
            for task in scoped.tasks
            if task.id in kept_ids
        ]

        scoped.target_task_id = target_id

        report = await resolve(
            scoped,
            CoreScheduler(time_limit=ANALYZE_TIME_LIMIT),
            settings,
            assume_conflict=True,
            hint=baseline.chunks,
        )

        # Task khác vẫn chưa xếp được: option nào cũng không giải quyết
        # chúng, nên ghi rõ để bảng lịch hoàn chỉnh không gây hiểu lầm.
        others = {
            task_id: minutes
            for task_id, minutes in baseline.unscheduled.items()
            if task_id != target_id
        }

        for option in report.options:
            option.unplaced = dict(others)

        self.reports[target_id] = (
            report,
            scoped,
        )

        return report
    def apply(
        self,
        target_id,
        option_id,
        expected_version,
        duration=None,
    ):
        if expected_version != self.context.schedule_version:
            raise ValueError(
                "Lịch đã đổi; hãy phân tích lại conflict."
            )

        if target_id not in self.reports:
            raise ValueError(
                "Cần phân tích trước khi áp dụng."
            )

        report, scoped = self.reports[target_id]

        if report.schedule_version != expected_version:
            raise ValueError(
                "Phương án đã cũ."
            )

        option = next(
            option
            for option in report.options
            if option.option_id == option_id
        )

        if not option.is_available:
            raise ValueError(
                "Phương án không khả dụng."
            )

        candidate = scoped.model_copy(deep=True)
        payload = option.action_payload

        # Lịch đã kiểm chứng lúc analyze dùng làm gợi ý cho solver.
        hint = option.preview

        target = next(
            task
            for task in candidate.tasks
            if task.id == target_id
        )

        if option_id == 1:
            candidate.tasks = [
                task
                for task in candidate.tasks
                if task.id != target_id
            ]

        elif option_id == 2:
            value = (
                payload["new_duration"]
                if duration is None
                else duration
            )

            if (
                not isinstance(value, int)
                or not (
                    target.min_remaining_min
                    <= value
                    <= payload["new_duration"]
                )
            ):
                raise ValueError(
                    "Thời lượng ngoài phạm vi gợi ý."
                )

            target.remaining_min = value

            # Thời lượng khác mức đã kiểm chứng thì hint không còn khớp.
            if value != payload["new_duration"]:
                hint = ()

        else:
            for change in payload["changes"]:
                operation = change["operation"]

                if operation == "REMOVE_FIXED":
                    # Xóa cả lần diễn ra: sự kiện + chuẩn bị + đi về.
                    dropped = set(change["task_ids"])

                    candidate.fixed_tasks = [
                        item
                        for item in candidate.fixed_tasks
                        if item.id not in dropped
                    ]

                elif operation == "EXPAND_ACTIVE_WINDOW":
                    window = candidate.active_windows[
                        change["window_index"]
                    ]

                    window.start = change["new_start"]
                    window.end = change["new_end"]

                else:
                    raise ValueError(
                        f"Thao tác không hỗ trợ: {operation}"
                    )

        kept_chunks = []

        # Kiểm tra trên bản sao trước khi cập nhật thật.
        if candidate.tasks:
            remaining_ids = {
                task.id
                for task in candidate.tasks
            }

            # Nếu target vừa bị xóa, chuyển tham chiếu
            # sang một task còn tồn tại trước khi validate.
            if candidate.target_task_id not in remaining_ids:
                candidate.target_task_id = candidate.tasks[0].id

            candidate = ConflictContext.model_validate(
                candidate.model_dump()
            )

            result = CoreScheduler().plan(
                candidate,
                hint=hint,
            )

            if result.status == "UNKNOWN":
                raise SolverInconclusive(
                    "Chưa kiểm chứng được lựa chọn do hết thời gian; chưa thay đổi lịch."
                )

            if result.status != "FEASIBLE":
                raise ValueError(
                    "Lựa chọn chưa xếp được đầy đủ; chưa thay đổi lịch."
                )

            kept_chunks = list(result.chunks)

        updated = self.context.model_copy(deep=True)

        scoped_ids = {
            task.id
            for task in scoped.tasks
        }

        updated.tasks = [
            task
            for task in updated.tasks
            if task.id not in scoped_ids
        ] + candidate.tasks

        if updated.tasks:
            remaining_ids = {
                task.id
                for task in updated.tasks
            }

            if updated.target_task_id not in remaining_ids:
                updated.target_task_id = updated.tasks[0].id

        updated.fixed_tasks = candidate.fixed_tasks
        updated.active_windows = candidate.active_windows
        updated.schedule_version += 1

        self.context = updated

        # Bảo vệ các task đã giữ khi xử lý conflict tiếp theo.
        self.protected_ids = {
            task.id
            for task in candidate.tasks
        }

        # Lần xếp baseline kế tiếp xuất phát từ lịch đã kiểm chứng,
        # thay vì giải lại từ đầu.
        self.hint_chunks = kept_chunks

        self.cached_plan = None
        self.reports.clear()

        return self.plan()
