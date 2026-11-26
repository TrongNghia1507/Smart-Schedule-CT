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

## Phạm vi phiên bản

Đã triển khai phần luồng nhập, các luật V/F/G, bảng và form, lịch tuần, CSV, JSON và snapshot. XLSX, kéo thả lịch và xếp việc deadline chưa triển khai theo phạm vi đã thống nhất.

Giao diện bám bố cục preview: header xanh, khung bảng, badge, lịch tuần và panel tóm tắt. Form sửa là hộp thoại Streamlit, chưa neo cạnh khối lịch như hình. Ô giờ cố định hỗ trợ HH:mm/24:00. Bảng dùng component HTML riêng với theme đồng bộ và sửa trực tiếp; lỗi được hiển thị theo dòng và ngay dưới bảng.


## Kiểm thử

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/input
```

Component lịch: https://github.com/im-perativa/streamlit-calendar
API giao diện: https://docs.streamlit.io/develop/api-reference
# Cập nhật giao diện nhập và preview

- Nhập CSV dùng một file cho cả hai loại task, phân biệt bằng cột `task_type` (`fixed`/`deadline`). Trong mục Nhập CSV có khung **ⓘ Hướng dẫn input** mặc định đóng, kèm ví dụ theo tuần đang lập lịch và nút tải mẫu. Các cột không áp dụng để trống; dữ liệu được thêm vào danh sách hiện tại. Nút **Xuất tất cả task CSV** xuất cùng định dạng để có thể nhập lại. File CSV cũ thiếu `task_type` cần thêm cột này trước khi nhập qua UI.

- Kéo thả dùng callback của streamlit-calendar 1.5 và vùng `st.fragment`: lưu/kiểm tra trước khi cập nhật preview, giữ nguyên key của calendar để không tạo lại iframe sau mỗi lần kéo. Snapshot cũ được vô hiệu hóa khi lưu thành công; thao tác bị từ chối sẽ đồng bộ lại lịch đã lưu. Các callback cũ không được áp dụng lần thứ hai.

- Chạy `start.ps1 -Background` sẽ giữ web bằng `serve_forever.py`: khi tiến trình Streamlit thoát, nó được khởi động lại sau khoảng 3 giây. F5 mở lại phiên từ bản nháp đã lưu; nội dung form chưa bấm Lưu có thể mất. `stop.ps1` dừng cả supervisor và server. Tính năng này không tự bật máy hoặc tự chạy sau khi Windows khởi động lại.

- Fixed task có `prep_min` (0–90 phút, mặc định 0). Khoảng chuẩn bị nằm trước giờ bắt đầu, được tính khi kiểm tra chồng lịch và hiển thị trên preview. File nháp cũ thiếu trường này vẫn đọc được với giá trị 0. Adapter MVP hiện hỗ trợ trường này.
- Chọn **Không có hạn chót cụ thể** để dùng 23:59 Chủ nhật của tuần đang lập lịch. Form ẩn ngày/giờ khi chọn; JSON chỉ lưu `deadline`, không thêm cờ free deadline. Khi đổi tuần, deadline đã lưu vẫn là mốc ngày cụ thể.
- Preview cho kéo việc cố định theo bước 10 phút, giữ nguyên thời lượng. Việc lặp được di chuyển cả chuỗi (các thứ lặp dịch theo số ngày kéo). Nếu validation báo lỗi thì thay đổi không được lưu. Công việc deadline chưa có vị trí lịch nên chưa kéo được ở preview input.
- Trong cửa sổ sửa việc ở preview có bảng màu hai hàng và nút Mặc định. Màu được lưu ở `calendar_colors.json` cạnh file nháp, không đưa vào snapshot/task JSON. Khoảng ngủ và chuẩn bị không kéo được.

- Fixed task có thêm `after_min` (0–60 phút, mặc định 0), giữ chỗ ngay sau giờ kết thúc. Khoảng này được lưu trong bản nháp/CSV/snapshot, hiển thị trên preview và tính vào kiểm tra chồng lịch, thời gian trống. Adapter MVP chuyển tiếp trường này.
