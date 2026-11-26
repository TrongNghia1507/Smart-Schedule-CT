# API của ứng dụng React

FastAPI cung cấp OpenAPI ở `/docs` và `/openapi.json`. React và API dùng chung origin. Vite chuyển tiếp `/api` tới localhost cổng 8000 khi phát triển.

## Phiên đăng nhập

`POST /api/v1/auth/login` và `POST /api/v1/auth/register` trả `{user, csrf}` và cookie HTTP-only có hạn 12 giờ. `GET /api/v1/auth/me` khôi phục thông tin phiên. Khi ghi, gửi `X-CSRF-Token` với giá trị `csrf`. `POST /api/v1/auth/logout` thu hồi phiên. API lấy chủ sở hữu và vai trò từ cơ sở dữ liệu.

## Tuyến chính

| Tiền tố sau `/api/v1` | Thao tác |
| --- | --- |
| `/draft` | Đọc nháp, kiểm tra, tải snapshot, gửi lệnh chỉnh sửa với `expected_revision`, xem trước lịch tuần |
| `/draft/imports` | Gửi CSV dạng octet-stream để xem trước hoặc nhập. Bước nhập nhận `expected_revision` của lần xem trước. `GET /draft/example` tải CSV mẫu theo tuần |
| `/plans` | Xếp từ nháp, xem kế hoạch và tiếp tục sau khi tải lại. Khi tạo kế hoạch gửi `expected_revision` và `operation_id` |
| `/plans/{id}/conflicts`, `/apply` | Phân tích, xem lịch theo phương án và áp dụng với `expected_version`. Bước áp dụng nhận `operation_id` và tự ghi một phiên bản lịch sử |
| `/plans/{id}/history`, `/finalize`, `/download` | Lưu lịch, chốt và tải JSON. Khi lưu lịch sử thủ công gửi `operation_id` |
| `/history` | Lọc theo tuần, đọc lịch, xuất JSON, nạp vào nháp theo revision hoặc xóa |
| `/ratings` | Đọc biểu mẫu, đánh giá đã lưu và cập nhật theo khóa lịch đã chốt |
| `/admin` | Tổng quan, xuất CSV theo bộ lọc và đổi mật khẩu. Yêu cầu vai trò admin |
| `/health`, `/ready` | Liveness và kiểm tra SQLite đã sẵn sàng |

`operation_id` là UUID mới cho mỗi ý định xếp, áp dụng hay lưu lịch. Khi gửi lại cùng thao tác sau mất kết nối, dùng UUID và tham số cũ. Dùng một UUID cho hai thao tác khác nhau trả 409. Kế hoạch ghi kết quả solver sau khi kiểm tra lại phiên bản dữ liệu. Chốt cùng một lịch dùng cùng khóa và giữ một bản ghi cho mỗi người dùng.

Lỗi API trả `{code, message, issues}`. HTTP 401 yêu cầu đăng nhập, 403 thiếu quyền hoặc CSRF không hợp lệ, 404 tài nguyên không thuộc phiên hoặc không tồn tại, 409 phiên bản đã đổi, 422 dữ liệu không hợp lệ, 503 khi solver chưa kết luận. Tuyến tích hợp trước đây `GET /health` và `POST /conflicts/analyze` duy trì hợp đồng từ `conflict_resolver.api`.

## Chuyển dữ liệu từ Streamlit

Chạy trên bản sao của thư mục dữ liệu cũ, gồm `portal.db` và `users/`. Dừng lượt ghi Streamlit trước khi sao lưu đồng bộ và trước lần nhập dữ liệu dùng để chuyển sang React. `--source-db` cho phép chỉ định SQLite ở vị trí riêng. Mặc định công cụ chỉ kiểm kê. Truyền `--apply` để tạo và ghi vào SQLite đích riêng biệt.

```powershell
python -m backend.web.migrate --source-dir apps/streamlit/data --destination .data/portal.db
python -m backend.web.migrate --source-dir apps/streamlit/data --destination .data/portal.db --apply
```

Công cụ dùng SQLite Backup API cho tài khoản, lượt đăng nhập, lịch đã chốt và đánh giá. Sau đó công cụ nhập nháp, màu và lịch sử theo ID tài khoản. Bản nháp chính là `schedule_input_draft.json`. Công cụ báo file nháp thay thế, dòng lỗi và người dùng thiếu đối chiếu. Công cụ giữ thứ tự và ID bản ghi hợp lệ. Lần chạy lại bỏ qua nháp đã có và lịch sử đã nhập. Đối chiếu tổng số và kiểm tra mục `issues` trên bản sao trước khi đổi môi trường phục vụ.

Ứng dụng đọc `SCHEDULE_PORTAL_DB` nếu được đặt, nếu không sẽ dùng `portal.db` trong `SCHEDULE_WEB_DATA_DIR` (mặc định `.data`). Trên Docker, mount volume vào `/data`. Chuyển về nhánh Streamlit dùng bản sao cũ, nên cần giữ thêm bản SQLite của React nếu đã phát sinh lượt ghi sau khi chuyển. Chưa có công cụ đồng bộ ngược nháp và lịch sử SQLite sang JSON.
