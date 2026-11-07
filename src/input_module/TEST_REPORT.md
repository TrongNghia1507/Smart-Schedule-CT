# Kết quả kiểm thử

Ngày kiểm tra: 07/11/2026.

Kết quả: **36 kiểm thử tự động đạt**, gồm nghiệp vụ/parser/lưu trữ, migration v1 → v2, importance 1–3, dữ liệu mẫu theo giờ thật và giao diện bằng Streamlit AppTest. Đổi theme sáng/tối và chuyển trang giữ theme đã qua kiểm thử.

- Bộ vàng: 6 DeadlineTask, 3 FixedTask, không Error; V06 một lần, V13 hai lần, V14 hai lần; 16 khối Preview và 14 dải ngủ mặc định.
- Qua nửa đêm, ranh giới tuần, 24:00, hai khoảng tiếp giáp không chồng nhau.
- Giờ ngủ luôn lấy từ thiết lập chung; is_sleep cũ không thay dải ngủ; công việc bật linh hoạt nhưng cứng 100% vẫn bị kiểm tra chồng giờ cứng.
- Gộp khoảng bận khi tính G01; không trừ thời gian chồng nhau hai lần.
- Phân tích nhiều định dạng, lỗi nhiều trường trong một lần, buffer bước 5.
- Snapshot bất biến; JSON lưu/đọc lại; deadline cũ được giữ; bảo vệ file hỏng/phiên bản mới.
- CSV round-trip cả hai loại; nhập một phần khi có dòng không hợp lệ.
- Giao diện: mở trang nhập; nạp mẫu → Preview → snapshot; không có nhân bản/mốc giả lập/is_sleep; importance 3 nấc; Sáng/Tối qua lại và chuyển trang.
- Song ngữ: Vie → Eng → Vie qua hai trang và theme tối giữ nguyên mọi công việc; form và lỗi tiếng Anh; đọc ngôn ngữ từ URL; bảng lặp tiếng Anh round-trip qua parser không đổi task; locale lịch đổi nhưng sự kiện không đổi.

Ứng dụng phục vụ tại `http://127.0.0.1:8501`; endpoint `/_stcore/health` trả **HTTP 200 / ok** khi kiểm tra.

AppTest không thay thế nghiên cứu với 3–5 người dùng. Giao diện dùng modal Streamlit thay popup neo cạnh khối, như README mô tả. Component bảng đã được mở trên trình duyệt và kiểm tra nút Sửa gọi đúng công việc.

Đã kiểm tra trình duyệt bản song ngữ: Eng tại trang nhập (nhãn bảng, thứ, độ co dãn và thông báo), lịch Eng ở chế độ tối, chuyển lại Vie giữ theme tối; lịch đổi thứ/ngày đúng locale. Nút ngôn ngữ đồng bộ màu cả hai theme. Ảnh kiểm chứng: `../preview-vie-eng.jpg`. Không nạp mẫu hoặc sửa dữ liệu thật trong bước kiểm tra trình duyệt.

Môi trường kiểm thử giao diện cần socket nội bộ. Sandbox chặn socket, nên các lần kiểm thử AppTest đạt được chạy ngoài sandbox. Bộ kiểm thử nghiệp vụ cũng đã đạt độc lập trong workspace.

Mỗi lần lặp và dải giờ ngủ có ID hiển thị riêng; đã kiểm tra bộ mẫu có 30 ID duy nhất (16 sự kiện + 14 dải ngủ), đồng thời các khối vẫn liên kết về task_id gốc để sửa.
