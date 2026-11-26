# Dịch vụ backend MySQL và TiDB

Tài liệu này mô tả lớp dịch vụ MySQL và TiDB. Điểm chạy hiện tại của React là `backend.web.app:app`, dùng API và SQLite theo [hướng dẫn web](api-v1.md).

Backend gồm các hàm Python. Các hàm theo tài khoản nhận `user_id` và `week_start` (ngày Thứ Hai, kiểu `date`).

## Chạy lần đầu

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env 
.\.venv\Scripts\python.exe -m backend.init_db     # tạo bảng (thêm --drop để tạo lại từ đầu)
```
## Sửa file .env trỏ thẳng lên TiDB Cloud
``` 
DB_HOST=gateway01.ap-southeast-1.prod.aws.tidbcloud.com
DB_PORT=4000
DB_USER=xxxx.root
DB_PASSWORD=mat_khau_tidb_cua_ban
DB_NAME=smart_schedule_ct
DB_SSL=true
```

## Chạy ứng dụng

Xem [README](../README.md) để build React và chạy FastAPI.
## Các service

| Module | Hàm chính | Bảng |
| --- | --- | --- |
| `auth_service` | `register`, `login`, `get_user` | users |
| `mysql_task_repo` | `MySQLTaskRepository(user_id, week_start)` (`load` / `save`), `load_task_colors`, `save_task_color`, `get_week_settings`, `save_week_settings` | user_week_settings, fixed_tasks, deadline_tasks |
| `schedule_service` | `run_schedule`, `get_schedule_view`, `get_latest_schedule`, `list_schedules`, `validate_week`, `update_policy_settings`, `analyze_conflict`, `get_conflict_options`, `apply_conflict_option` | schedules, schedule_blocks, conflict_options (+ ghi schedule_histories khi áp dụng) |
| `history_service` | `save_manual_history`, `list_histories`, `get_history_detail`, `get_history_download`, `update_history_meta`, `delete_history`, `restore_history_input` | schedule_histories |
| `ics_service` | `export_schedule_ics` | schedule_blocks |
| `feedback_service` | `submit_feedback`, `get_feedback`, `export_all_feedbacks_csv`, `get_summary_stats` | feedbacks |

Mọi lỗi nghiệp vụ là `backend.errors.BackendError` (có `.code`, `.message`, `.details`). `SolverInconclusive` (solver hết giờ) đi từ `conflict_resolver.errors`; hãy bắt cả hai và cho phép "Thử lại".

## Luồng gọi từ UI

```python
from datetime import date
from backend import auth_service, schedule_service, history_service, feedback_service, ics_service
from backend.mysql_task_repo import MySQLTaskRepository

user = auth_service.login("22120001", "matkhau")            # lưu user["id"] vào st.session_state
repo = MySQLTaskRepository(user["id"], week_start)          # thay JsonFileRepository trong app.py
# TaskInputService(data, repo) dùng như cũ; mọi lần submit/remove/undo tự ghi vào MySQL.

schedule_service.update_policy_settings(user["id"], week_start, 30, 30)
view = schedule_service.run_schedule(user["id"], week_start, lang="vi")
# view["events"]  -> dữ liệu lịch FullCalendar
# view["unscheduled"] -> danh sách task kẹt: [{task_code, name, missing_minutes, ...}]

if view["unscheduled"]:
    code = view["unscheduled"][0]["task_code"]
    analysis = schedule_service.analyze_conflict(user["id"], view["schedule_id"], code)
    # analysis["options"]: 3 thẻ; mỗi thẻ có preview_events, ai_explanation, duration_slider
    view = schedule_service.apply_conflict_option(
        user["id"], view["schedule_id"], code, option_code=2, chosen_duration_min=100,
        expected_version=view["schedule_version"])        # trả view của LỊCH MỚI + tự lưu history

history_service.save_manual_history(user["id"], view["schedule_id"])
feedback_service.submit_feedback(user["id"], view["schedule_id"], {
    "criteria": {
        "coverage":    {"satisfaction": 5, "importance": 5},
        "priority":    {"satisfaction": 5, "importance": 5},
        "deadline":    {"satisfaction": 4, "importance": 4},
        "continuity":  {"satisfaction": 4, "importance": 3},
        "balance":     {"satisfaction": 4, "importance": 4},
        "constraints": {"satisfaction": None, "importance": 3},  # None hoặc "Không áp dụng"
        "feasibility": {"satisfaction": 4, "importance": 5},
    },
    "tradeoffs": [2, 3, 4, 2, 3],                 # 1..5 hoặc nhãn "Hẳn A" .. "Hẳn B"
    "overall_satisfaction": 4,
    "usage_intent": "minor_edits",                # nhận cả mã hoặc nhãn tiếng Việt trên form
    "vs_self_scheduling": "slightly_better",
    "nps_score": 8,                               # 0..10
    "conflict_clarity_score": 4,                  # 1..5 hoặc None nếu không có xung đột
    "reported_issues": ["too_many_small_chunks"], # mảng mã hoặc nhãn pill tiếng Việt
    "best_aspect": "Xếp đủ toàn bộ việc bắt buộc.",
    "needs_improvement": "Có ngày hơi dày.",
})
name, ics_text = ics_service.export_schedule_ics(user["id"], view["schedule_id"])
csv_bytes = feedback_service.export_all_feedbacks_csv(admin_password)   # khu vực Admin
```

## Quy ước

- `user_id` do UI lấy từ phiên đăng nhập; mọi truy vấn đều lọc theo `user_id`. Truy cập tài nguyên của người khác → `NotFoundError`.
- Mốc `now`: tuần tương lai tính từ 00:00 Thứ Hai, tuần hiện tại giữ giờ thật (múi giờ `Asia/Ho_Chi_Minh`), tuần đã qua → `WeekAlreadyOverError`.
- Mỗi lịch `NOT_FOUND` chỉ áp dụng được **1** phương án; sau đó làm tiếp trên lịch mới (`apply_conflict_option` trả về lịch mới).
- Trạng thái solver nằm trong `schedules.solver_state_json`, nên F5 hay khởi động lại server vẫn tiếp tục phân tích / áp dụng được.
- `history`: mỗi lần áp dụng phương án tự tạo 1 phiên bản; `save_manual_history` tạo thêm khi người dùng bấm lưu. Mỗi phiên bản lưu kèm dữ liệu nhập (`input_snapshot_json`) nên `restore_history_input` khôi phục được bảng công việc của tuần đó.
