# Smart Schedule CT

Ứng dụng lập lịch tuần. Người dùng nhập công việc và sự kiện cố định, xem lịch đề xuất và chọn cách xử lý khi một công việc chưa xếp được.

## Cấu trúc theo mô-đun

```text
.
├── apps/
│   └── web/                   # React, TypeScript, Vite và FullCalendar
├── src/
│   ├── backend/web/           # FastAPI, phiên đăng nhập và lưu trữ SQLite
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

Ứng dụng web dùng Python 3.11 trở lên và Node 24. Ví dụ trên PowerShell, với Python 3.12 đã cài:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm --prefix apps/web ci
npm --prefix apps/web run build
.\.venv\Scripts\python.exe -m uvicorn backend.web.app:app --host 127.0.0.1 --port 8501
```

Mở [Smart Schedule CT](http://127.0.0.1:8501/app/). Trên Linux hoặc Codespaces, dùng `.venv/bin/python` hoặc kích hoạt môi trường bằng `source .venv/bin/activate`. Để dùng cổng đã forward trong Codespaces, bind Uvicorn vào `0.0.0.0` và giữ cổng ở chế độ riêng tư.

Khi phát triển frontend, chạy FastAPI ở cổng 8000 và mở một terminal khác để chạy Vite:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.web.app:app --reload --port 8000
npm --prefix apps/web run dev
```

Vite phục vụ `http://localhost:5173/app/`. Nếu dùng Docker, `docker compose up --build web` build và phục vụ giao diện cùng API tại cổng 8501, dùng volume `schedule_data` cho SQLite.

Tài khoản admin có tên `admin`. Đặt biến môi trường `SCHEDULE_ADMIN_PASSWORD` trước lần khởi động đầu tiên để chọn mật khẩu. Khi dùng HTTPS, đặt `SCHEDULE_SECURE_COOKIE=true` và dùng mật khẩu admin đã đổi. Uvicorn phục vụ giao diện build ở `/app/` và chuyển hướng `/` tới đó. Môi trường build và runtime mặc định chỉ cài thư viện cho React và FastAPI.

Ứng dụng mới dùng SQLite trong `.data/portal.db` khi chạy trực tiếp. Nếu có tài khoản, nháp hoặc lịch sử từ bản cũ, dùng [hướng dẫn chuyển dữ liệu](docs/api-v1.md#chuyển-dữ-liệu-từ-streamlit) trước khi khởi động với cơ sở dữ liệu đích.

## Kiểm thử

```powershell
.\.venv\Scripts\python.exe -m pip install pytest -r apps/streamlit/requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
npm --prefix apps/web run typecheck
.\.venv\Scripts\python.exe -m schedule_preparation.run_json examples/gui_snapshot.json --only validate
.\.venv\Scripts\python.exe -m scheduling_algorithm.main examples/solver/input_test.json -o schedule_result.json
```

Mã Streamlit trong repo phục vụ kiểm thử hồi quy đối chiếu với bản trước khi chuyển giao diện. Nhánh gốc `test_connect_conclusion` vẫn là điểm quay lại khi cần chạy riêng bản Streamlit với bộ dữ liệu cũ.

Chi tiết về [API React](docs/api-v1.md), [nhập liệu](docs/input.md), [bộ xếp lịch](docs/solver.md) và [hợp đồng xử lý xung đột](docs/conflict-contract.md).
