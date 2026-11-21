# Schedule Management — khối Input

Giao diện Streamlit cho nhập việc cố định và việc có hạn chót, kiểm tra dữ liệu, xem lịch tuần và tạo InputSnapshot. Từ trang xem trước, người dùng có thể chạy xếp lịch qua mô-đun xử lý xung đột.

## Chạy trên máy

Mở PowerShell tại thư mục gốc của repo với Python 3.12 trở lên.

```powershell
.\apps\streamlit\setup.ps1
.\apps\streamlit\start.ps1 -Background
# Mở http://127.0.0.1:8501
.\apps\streamlit\stop.ps1
```

`setup.ps1` cài các mô-đun của dự án và thư viện giao diện vào `.venv` ở thư mục gốc. Có thể truyền `-Python` khi cần chỉ định đường dẫn Python và `-Port 8502` cho `start.ps1` nếu cổng mặc định bận.

## Chạy trên codespaces

Lệnh set up chạy lần đầu: 

```
python -m venv .venv
source .venv/bin/activate
python -m pip install -e . -r apps/streamlit/requirements.txt
export TZ=Asia/Ho_Chi_Minh
``` 

Lệnh chạy streamlit:

```
python -m streamlit run apps/streamlit/app.py \
  --server.address 0.0.0.0 \
  --server.port 8501 \
  --server.headless true
```

## Sử dụng

1. Chọn tuần Thứ Hai và giờ ngủ trong Thiết lập chung. Ứng dụng luôn dùng giờ hiện tại. Nút Dữ liệu mẫu nạp 9 việc và dời hạn chót sang tuần tới sau khi xác nhận thay dữ liệu.
2. Nhập bằng form hoặc nhấp đúp/Enter tại ô bảng để sửa trực tiếp. Bấm tiêu đề từng khung để thu gọn hoặc mở rộng; bảng dài cuộn bên trong khung. Bảng tự lưu thay đổi hợp lệ. Có nút Sửa/Xóa trên từng dòng và Hoàn tác. Việc có hạn chót có ô **Bắt buộc** và mức quan trọng từ 1 đến 3.
3. CSV có hai loại bảng; xem lỗi từng dòng trước khi chọn nhập các dòng hợp lệ. Xuất dùng UTF-8 BOM.
4. Trang Xem trước lịch có lịch tuần bên trái, Tóm tắt và Chú giải bên phải. Bấm một khối để sửa cả chuỗi lặp. Giờ ngủ mặc định là các dải kẻ sọc mỗi ngày, không phải việc. Có thể xem lịch khi dữ liệu còn lỗi, nhưng không thể tạo snapshot.
5. Xác nhận tạo snapshot bất biến trong bộ nhớ. Nút xuất JSON chỉ phục vụ debug, không tự gọi Ranking.
6. Nút ☾ Tối / ☀ Sáng đổi màu cả hai trang, bảng, form và lịch. Lựa chọn được giữ khi chuyển trang và qua tham số theme trong URL khi tải lại.
7. Nút **Vie / Eng** cạnh Sáng/Tối đổi ngôn ngữ của hai trang, form, bảng, lịch, chú giải và thông báo kiểm tra. Lựa chọn được giữ khi chuyển trang và qua tham số `lang=vi` / `lang=en` trong URL khi tải lại. Tên việc, giờ và dữ liệu lưu không bị dịch hoặc thay đổi. Bảng tiếng Anh chấp nhận lịch lặp như `Mon, Thu` hoặc `Mon–Sun`.
8. **Xem tuần hiện tại** chỉ đổi tuần hiển thị để xem vạch giờ đỏ. Bấm **← Quay lại tuần đang lập lịch** để trở về. Hai nút không thay tuần lập lịch, file nháp hoặc dữ liệu snapshot. Khi mở tuần hiện tại, lịch cuộn đến khoảng một giờ trước giờ hiện tại.

File nháp mặc định là `apps/streamlit/data/schedule_input_draft.json`. Nếu chỉ có nháp ở `src/input_module/data/` từ bản cũ, ứng dụng sẽ tiếp tục dùng thư mục dữ liệu đó. Có thể chọn thư mục khác bằng `SCHEDULE_INPUT_DATA_DIR`. File lỗi cú pháp được giữ lại với tên có `corrupt` và thời gian. Phiên bản lược đồ không hỗ trợ được bảo vệ khỏi ghi đè. Việc có deadline cũ vẫn được giữ và báo lỗi để sửa. Nhật ký server ở `apps/streamlit/data/`.

## Kiến trúc

- `src/schedule_input/domain/` chứa mô hình và quy tắc nghiệp vụ.
- `src/schedule_input/application/` chứa parser, mapper, dịch vụ nhập và tạo snapshot.
- `src/schedule_input/infrastructure/` đọc và ghi JSON, CSV và dữ liệu mẫu.
- `src/schedule_input/ui/` chứa các thành phần giao diện nhập liệu và bản dịch.
- `apps/streamlit/app.py` nối giao diện nhập liệu với luồng xếp lịch.
- `tests/input/` kiểm thử nghiệp vụ, ca biên và giao diện.

## Quyết định đã chốt và hợp đồng tích hợp

- Buffer là bội số 5 trong 0–60.
- Việc cố định chiếm trọn khoảng giờ đã nhập. Dữ liệu cũ vẫn đọc được và các trường co dãn cũ được bỏ qua.
- Giờ ngủ chỉ lấy từ Thiết lập chung và luôn áp dụng mỗi ngày. Không suy luận tên công việc là giờ ngủ; trường is_sleep cũ không còn được nhập/xuất hoặc dùng để thay thế giờ ngủ.
- Schema JSON/snapshot là 2. File v1 được sao lưu thành `.v1.bak.json` trước khi đọc chuyển đổi: importance 1–3 → 1, 4–7 → 2, 8–10 → 3; bỏ now_override. Công việc cũ vẫn được giữ, kể cả việc ngủ đã nhập trước đây, để người dùng tự quyết định xóa nếu trùng.
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
