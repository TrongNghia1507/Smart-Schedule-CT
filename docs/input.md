# Nhập liệu cho lịch tuần

Mở ứng dụng theo [README](../README.md) và đăng nhập bằng tài khoản người dùng.

1. Chọn tuần bắt đầu vào Thứ Hai và giờ ngủ. **Nạp mẫu** thay bản nháp sau khi xác nhận và chuyển sang tuần tới.
2. Thêm việc bằng form hoặc sửa ngay dưới dòng trong bảng. Việc cố định có thể lặp theo ngày hoặc diễn ra một lần. Việc có hạn chót có mức quan trọng, thời lượng, độ dài phiên và nghỉ giữa phiên.
3. Với CSV, chọn **Kiểm tra CSV** để xem lỗi theo dòng rồi nhập các dòng hợp lệ. Nút xuất tạo tệp UTF-8 BOM.
4. Mở lịch tuần để xem sự kiện, giờ ngủ, chuẩn bị và di chuyển. Bấm việc cố định để sửa hoặc kéo theo bước 10 phút. Di chuyển việc lặp sẽ dời cả chuỗi. Khi chỉnh sửa bị từ chối, lịch đưa việc về vị trí cũ.
5. Chạy xếp lịch từ nháp đã kiểm tra. Có thể tải snapshot JSON, phân tích xung đột, lưu vào lịch sử hoặc chốt và đánh giá.
6. Tùy chọn ngôn ngữ và giao diện được lưu trong trình duyệt và hỗ trợ tham số `lang` và `theme`. **Tuần hiện tại** chỉ đổi tuần hiển thị.

Nháp và màu được lưu trong SQLite theo tài khoản. Khi hai tab chỉnh cùng một revision, tab gửi sau nhận yêu cầu tải dữ liệu mới. Xem [hướng dẫn chuyển dữ liệu](api-v1.md#chuyển-dữ-liệu-từ-streamlit) để nhập dữ liệu từ tệp cũ.

## Quyết định đã chốt và hợp đồng tích hợp

- Buffer là bội số 5 trong 0–60.
- Việc cố định chiếm trọn khoảng giờ đã nhập. Dữ liệu cũ vẫn đọc được và các trường co dãn cũ được bỏ qua.
- Giờ ngủ chỉ lấy từ Thiết lập chung và luôn áp dụng mỗi ngày. Không suy luận tên công việc là giờ ngủ; trường is_sleep cũ không còn được nhập/xuất hoặc dùng để thay thế giờ ngủ.
- Schema JSON/snapshot là 2. Công cụ nhập giữ nguyên file v1 nguồn khi chuyển đổi: importance 1–3 → 1, 4–7 → 2, 8–10 → 3; bỏ now_override. Công việc cũ vẫn được giữ, kể cả việc ngủ đã nhập trước đây, để người dùng tự quyết định xóa nếu trùng.
- Các occurrence giao với tuần được lấy cả từ ngày trước đầu tuần. Preview cắt biên tuần; snapshot giữ start/end gốc.
- G01 dùng phần tuần còn lại, trừ hợp các khoảng bận và giờ ngủ; nhu cầu gồm thời lượng và buffer. Không co việc để tính phút trống.
- `TimeRange` dùng phút từ nửa đêm trong nội bộ để biểu diễn được 24:00; JSON vẫn giữ HH:mm đúng plan.
- `window.sleep.default_bands` chứa các dải ngủ trong tuần; `is_default` luôn true. Consumer phải dùng schema 2 và thang importance 1–3.
- `InputSnapshot.to_json()` xuất JSON; `to_dict()` trả bản sao độc lập, không cho sửa payload gốc. Gọi qua `TaskInputService.confirm()` để kiểm tra lại trước khi bàn giao.

## Nhập CSV và chỉnh sửa lịch

- CSV dùng chung cho việc cố định và việc có hạn. Cột `task_type` nhận `fixed` hoặc `deadline`. Nút **Tải CSV mẫu** tạo ví dụ theo tuần đang lập lịch.
- Với việc chưa có hạn cụ thể, chọn **Không có hạn chót cụ thể** để dùng 23:59 Chủ nhật. Bản nháp lưu ngày giờ cụ thể.
- Các khối giờ ngủ, chuẩn bị và di chuyển có màu riêng. Trong bản nháp, việc cố định nhận màu tùy chọn và có thể kéo theo bước 10 phút.
- Trên điện thoại, lịch mở ở chế độ từng ngày. Chọn một ngày ở trên lịch hoặc chuyển sang **Cả tuần**.
