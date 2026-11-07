# Schedule Management — khối Input

Ứng dụng Python/Streamlit cho nhập việc cố định và việc có hạn chót, kiểm tra dữ liệu, xem lịch tuần và tạo InputSnapshot. Không thực hiện Ranking hoặc Scheduling.

## Chạy trên máy

Mở PowerShell tại thư mục dự án:

```powershell
.\start.ps1 -Background
# Mở http://127.0.0.1:8501
.\stop.ps1
```

Môi trường riêng của lần triển khai này nằm ở `../../work/.venv`. Khi chuyển dự án sang máy khác, cài Python 3.12+, chạy `setup.ps1`, rồi `start.ps1`. Có thể dùng `-Port 8502` nếu cổng mặc định bận. Không cần quyền administrator. Không thiết lập tự khởi động Windows.

## Chạy trên codespaces

Lệnh set up chạy lần đầu: 

```
cd src/input_module
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
export TZ=Asia/Ho_Chi_Minh
``` 

Lệnh chạy streamlit:

```
python -m streamlit run app.py \
  --server.address 0.0.0.0 \
  --server.port 8501 \
  --server.headless true
```

## Sử dụng

1. Chọn tuần Thứ Hai và giờ ngủ trong Thiết lập chung. Ứng dụng luôn dùng giờ hiện tại. Nút Dữ liệu mẫu nạp 9 việc và dời hạn chót sang tuần tới sau khi xác nhận thay dữ liệu.
2. Nhập bằng form hoặc nhấp đúp/Enter tại ô bảng để sửa trực tiếp. Bảng tự lưu thay đổi hợp lệ. Có nút Sửa/Xóa trên từng dòng và Hoàn tác. Importance chỉ có 1, 2, 3; không có nhân bản và trường is_sleep.
3. CSV có hai loại bảng; xem lỗi từng dòng trước khi chọn nhập các dòng hợp lệ. Xuất dùng UTF-8 BOM.
4. Trang Xem trước lịch có lịch tuần bên trái, Tóm tắt và Chú giải bên phải. Bấm một khối để sửa cả chuỗi lặp. Giờ ngủ mặc định là các dải kẻ sọc mỗi ngày, không phải việc. Có thể xem lịch khi dữ liệu còn lỗi, nhưng không thể tạo snapshot.
5. Xác nhận tạo snapshot bất biến trong bộ nhớ. Nút xuất JSON chỉ phục vụ debug, không tự gọi Ranking.
6. Nút ☾ Tối / ☀ Sáng đổi màu cả hai trang, bảng, form và lịch. Lựa chọn được giữ khi chuyển trang và qua tham số theme trong URL khi tải lại.
7. Nút **Vie / Eng** cạnh Sáng/Tối đổi ngôn ngữ của hai trang, form, bảng, lịch, chú giải và thông báo kiểm tra. Lựa chọn được giữ khi chuyển trang và qua tham số `lang=vi` / `lang=en` trong URL khi tải lại. Tên việc, giờ và dữ liệu lưu không bị dịch hoặc thay đổi. Bảng tiếng Anh chấp nhận lịch lặp như `Mon, Thu` hoặc `Mon–Sun`.
8. **Xem tuần hiện tại** chỉ đổi tuần hiển thị để xem vạch giờ đỏ. Bấm **← Quay lại tuần đang lập lịch** để trở về. Hai nút không thay tuần lập lịch, file nháp hoặc dữ liệu snapshot. Khi mở tuần hiện tại, lịch cuộn đến khoảng một giờ trước giờ hiện tại.

File nháp: `data/schedule_input_draft.json`. File lỗi cú pháp được giữ lại với tên có `corrupt` và thời gian. Phiên bản lược đồ không hỗ trợ được bảo vệ khỏi ghi đè. Việc có deadline cũ vẫn được giữ và báo lỗi để sửa. Nhật ký server ở `data/`.

## Kiến trúc

- `domain/`: mô hình bất biến, tập hợp dữ liệu và kiểm tra nghiệp vụ.
- `application/`: parser, mapper, use case, projection, snapshot, import preview.
- `infrastructure/`: JSON nguyên tử, CSV, dữ liệu mẫu trích từ plan.
- `app.py`: giao diện Streamlit và component FullCalendar.
- `ui/i18n.py`: bản dịch ở lớp hiển thị; dữ liệu nghiệp vụ và hợp đồng JSON/CSV giữ nguyên.
- `tests/`: bộ vàng, ca biên và smoke test giao diện.

## Quyết định đã chốt và hợp đồng tích hợp

- Buffer là bội số 5 trong 0–60; min_duration_min từ 1 phút.
- Việc có `min_duration_min == duration_min` là cứng dù bật is_flexible.
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
..\..\work\.venv\Scripts\python.exe -m pytest -q
# Hoặc trên máy đã chạy setup.ps1:
.\.venv\Scripts\python.exe -m pytest -q
```

Component lịch: https://github.com/im-perativa/streamlit-calendar
API giao diện: https://docs.streamlit.io/develop/api-reference
