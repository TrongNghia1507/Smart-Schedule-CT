# Smart Schedule CT

Ứng dụng lập lịch tuần. Người dùng nhập công việc và sự kiện cố định, xem lịch đề xuất và chọn cách xử lý khi một công việc chưa xếp được.

## Cấu trúc theo mô-đun

```text
.
├── apps/
│   └── streamlit/             # Điểm chạy giao diện và script khởi động
├── src/
│   ├── schedule_input/        # Nhập, kiểm tra và tạo InputSnapshot
│   ├── schedule_preparation/  # Chuẩn hóa dữ liệu tuần, kiểm tra sức chứa, chia việc
│   ├── scheduling_algorithm/  # Xếp lịch bằng OR-Tools CP-SAT
│   └── conflict_resolver/      # Lập lịch, phân tích xung đột và xem trước phương án
├── tests/                     # Kiểm thử nhập liệu, API và tích hợp
├── examples/                  # JSON mẫu cho các lệnh chạy riêng
├── scripts/                   # Công cụ chẩn đoán
└── docs/                      # Hướng dẫn và hợp đồng dữ liệu
```

## Luồng xử lý

1. `schedule_input` kiểm tra dữ liệu đã nhập và xuất `InputSnapshot` dạng JSON.
2. `conflict_resolver/planning.py` nhận snapshot, gọi `schedule_preparation` để chuẩn hóa mốc thời gian và tạo `ConflictContext`.
3. `conflict_resolver/scheduler.py` chuyển ngữ cảnh thành đầu vào của bộ giải CP-SAT. Khi còn việc chưa xếp được, `conflict_resolver/strategies/options.py` thử các điều chỉnh và kiểm tra lại với bộ xếp lịch trước khi tạo bản xem trước.

## Điểm mở rộng

| Khi cần | Bắt đầu từ |
| --- | --- |
| Đổi định dạng CSV | [`schedule_input/infrastructure/io.py`](src/schedule_input/infrastructure/io.py) |
| Thêm mục tiêu tối ưu, chẳng hạn ưu tiên hoàn thành sớm | [`scheduling_algorithm/core_algorithm/criteria.py`](src/scheduling_algorithm/core_algorithm/criteria.py), sau đó đặt trọng số trong `config.objective` khi chạy CLI hoặc trong [`CoreScheduler`](src/conflict_resolver/scheduler.py) khi chạy từ giao diện |
| Thêm phương án xử lý xung đột | [`conflict_resolver/strategies/options.py`](src/conflict_resolver/strategies/options.py) và chỗ gọi phương án trong [`resolver.py`](src/conflict_resolver/resolver.py) |

Ví dụ khi trình bày, hãy mở `criteria.py` và chỉ vào mục tiêu `early_finish` được đăng ký qua `@register`. Bộ giải chọn mục tiêu dựa trên tên và trọng số trong cấu hình. Nhóm có thể thêm mục tiêu ở cùng chỗ và tiếp tục dùng luồng nhập dữ liệu, xếp lịch và hiển thị hiện tại.

## Chạy từ thư mục gốc

```powershell
.\apps\streamlit\setup.ps1
.\apps\streamlit\start.ps1
```

Địa chỉ mặc định là `http://127.0.0.1:8501`. Xem thêm cách chạy nền hoặc chạy trên Linux trong [hướng dẫn giao diện](docs/input.md).

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m schedule_preparation.run_json examples/gui_snapshot.json --only validate
.\.venv\Scripts\python.exe -m scheduling_algorithm.main examples/solver/input_test.json -o schedule_result.json
```

Lệnh chuẩn bị dữ liệu trước đây là `python -m mvp.run_json`, hiện dùng `python -m schedule_preparation.run_json`.

Chi tiết về [bộ xếp lịch](docs/solver.md) và [hợp đồng xử lý xung đột](docs/conflict-contract.md).
