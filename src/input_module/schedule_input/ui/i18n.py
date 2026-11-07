"""Presentation-only translations. Task names and stored values are never translated."""
import re
import streamlit as st


EN = {
    'Xem tuần hiện tại': 'View current week',
    '← Quay lại tuần đang lập lịch': '← Back to planning week',
    'Đang xem tuần hiện tại. Tuần lập lịch và dữ liệu đã lưu được giữ nguyên.': 'Viewing the current week. Your planning week and saved data are unchanged.',
    'Vạch đỏ chỉ hiện trong tuần có ngày hôm nay. Tuần đang xem không chứa ngày hiện tại.': 'The red line appears only in the week containing today. The displayed week does not include today.',
    'Chuyển lịch sang tuần hiện tại': 'Change planning week to the current week',
    'Quản lý lịch tuần': 'Weekly schedule manager',
    'Nhập dữ liệu': 'Enter data', 'Xem trước lịch': 'Preview schedule',
    'Xem trước lịch tuần': 'Weekly schedule preview', 'Trang': 'Page',
    '☾ Tối': '☾ Dark', '☀ Sáng': '☀ Light', 'Ngôn ngữ': 'Language',
    'Sửa công việc': 'Edit task', 'Tên công việc': 'Task name',
    'Lặp hằng tuần': 'Repeat weekly', 'Ngày diễn ra': 'Date',
    'Giờ bắt đầu (HH:mm)': 'Start time (HH:mm)',
    'Giờ kết thúc (cho phép 24:00)': 'End time (24:00 allowed)',
    'Có thể chia nhỏ và co dãn': 'Allow splitting and shortening',
    'Thời lượng tối thiểu (phút)': 'Minimum duration (minutes)',
    'Loại': 'Type', 'Mức quan trọng': 'Importance',
    'asap: việc gấp · hard: hạn cứng · soft: hạn mềm': 'asap: urgent · hard: strict deadline · soft: flexible deadline',
    'Ngày hạn chót': 'Deadline date', 'Giờ hạn chót': 'Deadline time',
    'Thời lượng (phút, ví dụ 60 hoặc 1h30)': 'Duration (minutes, e.g. 60 or 1h30)',
    'Mức tập trung': 'Focus level', 'Nghỉ đệm sau cả việc': 'Break after the entire task (minutes)',
    'Tùy chọn nâng cao': 'Advanced options',
    'Bắt đầu sớm nhất (dd/mm/yyyy HH:mm, có thể để trống)': 'Earliest start (dd/mm/yyyy HH:mm, optional)',
    'Lưu': 'Save', 'Xóa việc này': 'Delete task', 'Hủy': 'Cancel',
    'Thông báo về dữ liệu đã mở': 'Loaded data notices',
    'File nháp được bảo vệ. Chọn file mới để tiếp tục.': 'The draft file is protected. Choose a new file to continue.',
    'Dùng file nháp mới': 'Use a new draft file',
    'File nháp đang dùng tuần cũ. Bạn muốn giữ tuần hay chuyển sang tuần hiện tại?': 'This draft uses an earlier week. Keep it or switch to the current week?',
    'Giữ tuần cũ': 'Keep earlier week', 'Chuyển sang tuần hiện tại': 'Switch to current week',
    'Thiết lập chung': 'General settings',
    'Tuần lập lịch (chọn Thứ Hai)': 'Planning week (choose Monday)',
    'Bắt đầu ngủ mặc định': 'Default sleep start', 'Kết thúc ngủ mặc định': 'Default sleep end',
    'Giờ ngủ được kẻ sọc trên lịch, không cần nhập thành công việc.': 'Sleep hours appear as striped bands on the calendar; no task entry is needed.',
    'Áp dụng thiết lập': 'Apply settings', 'Hãy chọn ngày Thứ Hai.': 'Please choose a Monday.',
    'Dữ liệu mẫu': 'Sample data', 'Hoàn tác': 'Undo', 'Xóa toàn bộ': 'Clear all',
    'Nạp mẫu sẽ thay dữ liệu hiện tại; có thể hoàn tác. Các hạn chót mẫu được dời sang tuần tới để dùng với giờ hiện tại.': 'Loading the sample replaces current data and can be undone. Sample deadlines are moved to next week to work with the current time.',
    'Xác nhận nạp mẫu': 'Confirm sample load', 'Xác nhận xóa toàn bộ': 'Confirm clear all',
    'A. Việc cố định': 'A. Fixed tasks', 'B. Việc có deadline': 'B. Deadline tasks',
    '+ Thêm bằng form': '+ Add with form',
    'Thay đổi chưa được lưu. Sửa lại ô hoặc hủy thay đổi.': 'Changes have not been saved. Correct the cell or discard the changes.',
    'Hủy thay đổi chưa hợp lệ': 'Discard invalid changes', 'Xuất dữ liệu bảng': 'Export table data',
    'Xuất CSV': 'Export CSV', 'Nhập CSV': 'Import CSV', 'Loại bảng': 'Table type',
    'Việc cố định': 'Fixed tasks', 'Việc có hạn chót': 'Deadline tasks',
    'Chọn CSV UTF-8': 'Choose a UTF-8 CSV file',
    'Xác nhận → Xem trước lịch': 'Confirm → Preview schedule',
    'Chi tiết kiểm tra dữ liệu': 'Validation details', 'Chi tiết kiểm tra': 'Validation details',
    'Tóm tắt': 'Summary', 'Chú giải': 'Legend',
    'Việc cố định (tên + giờ)': 'Fixed task (name + time)', 'Giờ ngủ': 'Sleep hours',
    'Thời gian hiện tại': 'Current time', '↔ Có thể chia nhỏ / co dãn': '↔ Splitting / shortening allowed',
    'Bấm vào một việc để sửa nhanh. Việc có deadline chưa được xếp nên chưa hiện ở đây.': 'Click a task to edit it. Deadline tasks have not been scheduled yet and are not shown here.',
    '← Quay lại nhập': '← Back to data', 'Đúng rồi, tiếp tục': 'Looks good, continue',
    'Đã tạo InputSnapshot, sẵn sàng cho Ranking.': 'InputSnapshot created and ready for Ranking.',
    'Xuất snapshot JSON để debug': 'Export snapshot JSON for debugging',
    'lỗi': 'errors', 'cảnh báo': 'warnings', 'ghi chú': 'notes',
    'Có': 'Yes', 'Không': 'No', 'Cứng 100%': 'Rigid 100%',
    'Hạn chót rạng sáng; hãy kiểm tra lại giờ.': 'Early-morning deadline; please check the time.',
    'Hạn chót ngoài tuần đang lập lịch.': 'The deadline is outside the planning week.',
    'Thời lượng không chia hết cho 5; cân nhắc làm tròn.': 'Duration is not a multiple of 5; consider rounding it.',
    'Bắt đầu sớm nhất phải trước hạn chót.': 'Earliest start must be before the deadline.',
    'Cửa sổ hiệu dụng được nâng lên mốc bây giờ.': 'The effective start is adjusted to the current time.',
    'Dùng nguyên thời lượng làm một khối.': 'The entire duration will be used as one block.',
    'Chunk max hiệu dụng được giới hạn bằng thời lượng.': 'Effective maximum chunk length is capped at the task duration.',
    'Việc này sẽ được xếp liền 1 khối.': 'This task will be scheduled as one continuous block.',
    'Khoảng khả dụng ngắn hơn thời lượng cộng nghỉ đệm.': 'The available window is shorter than the duration plus break.',
    'Trùng tên với việc khác; kiểm tra có nhập trùng không.': 'Another task has the same name; check for a duplicate entry.',
    'Ngày diễn ra ngoài tuần đang lập lịch.': 'The task date is outside the planning week.',
    'Việc kéo sang hôm sau, lịch hiển thị thành các đoạn theo ngày.': 'This task continues into the next day and is displayed in daily segments.',
    'Chạm giờ ngủ mặc định; kiểm tra lại giờ.': 'This task overlaps default sleep hours; check the time.',
    'Hai việc ngủ chồng nhau; kiểm tra nhập trùng.': 'Two sleep tasks overlap; check for duplicates.',
    'Hãy nhập ít nhất một việc.': 'Please enter at least one task.',
    'Trên 100 việc một loại; hiệu năng có thể giảm.': 'There are over 100 tasks of one type; performance may decrease.',
    'Cần số nguyên.': 'An integer is required.', 'Tên bắt buộc, tối đa 100 ký tự.': 'A name is required, with a maximum of 100 characters.',
    'Chunk max phải lớn hơn hoặc bằng min.': 'Maximum chunk length must be at least the minimum.',
    'Nhập số phút nguyên, ví dụ 60, 60p hoặc 1h30.': 'Enter whole minutes, e.g. 60, 60m or 1h30.',
    'Nhập ngày giờ dd/mm/yyyy HH:mm hoặc ISO không múi giờ.': 'Enter dd/mm/yyyy HH:mm or an ISO date and time without a timezone.',
    'Nhập ngày dd/mm/yyyy.': 'Enter a date as dd/mm/yyyy.', 'Nhập giờ HH:mm.': 'Enter a time as HH:mm.',
    'Giờ phải từ 00:00 đến 23:59; kết thúc có thể là 24:00.': 'Time must be between 00:00 and 23:59; end time may be 24:00.',
    'Chọn Có hoặc Không.': 'Choose Yes or No.',
    'Dùng T2, T5 hoặc T2->CN; không dùng khoảng ngược.': 'Use Mon, Thu or Mon->Sun; reverse ranges are not allowed.',
    'Giờ phải hợp lệ và bắt đầu khác kết thúc.': 'Enter valid times; start and end must differ.',
    'Chọn thứ hoặc ngày diễn ra, không chọn cả hai.': 'Choose weekdays or a single date, not both.',
    'Chunk phải dương, min không vượt max.': 'Chunk lengths must be positive; minimum must not exceed maximum.',
    'Buffer từ 0–60, chia hết cho 5.': 'Break must be between 0 and 60 minutes, in multiples of 5.',
    'ID trùng.': 'Duplicate ID.', 'ID trùng trong bảng.': 'Duplicate ID in the table.',
    'Còn lỗi; chưa thể bàn giao.': 'Resolve the errors before continuing.',
    'File không tương thích đang được bảo vệ; chọn nơi lưu khác.': 'The incompatible file is protected; choose another save location.',
    'Phiên bản file không được hỗ trợ. File gốc được bảo vệ, chưa cho phép ghi đè.': 'Unsupported file version. The original file is protected from being overwritten.',
    'Đã đọc dữ liệu cũ: importance 1–3 → 1, 4–7 → 2, 8–10 → 3. Đã giữ bản sao v1; giờ hiện tại và giờ ngủ trong Thiết lập chung được áp dụng.': 'Legacy data loaded: importance 1–3 → 1, 4–7 → 2, 8–10 → 3. A v1 backup was retained; the current time and general sleep settings are applied.',
    'Tuần phải bắt đầu Thứ Hai.': 'The week must start on Monday.',
    'importance không hợp lệ': 'Invalid importance', 'ID trùng: đã cấp ID mới.': 'Duplicate ID: a new ID was assigned.',
}

# Anchored templates preserve inserted task names, dates, filenames and numbers verbatim.
PATTERNS = [
    (r'Thời lượng: (\d+) phút', r'Duration: \1 minutes'),
    (r'A\. Việc cố định · (\d+) việc', r'A. Fixed tasks · \1 tasks'),
    (r'B\. Việc có deadline · (\d+) việc', r'B. Deadline tasks · \1 tasks'),
    (r'\*\*(\d+) việc cố định\*\*', r'**\1 fixed tasks**'),
    (r'(\d+) khối · (\d+) dải ngủ mặc định', r'\1 blocks · \2 default sleep bands'),
    (r'Dòng (\d+)', r'Row \1'), (r'Nhập (\d+) dòng hợp lệ', r'Import \1 valid rows'),
    (r'Bỏ qua cột: (.*)', r'Ignored columns: \1'),
    (r'(\d+) giờ (\d+)', r'\1 h \2 min'), (r'(\d+) phút', r'\1 min'),
    (r'Co dãn ([\d.]+)% · rút tối đa (\d+) phút', r'Flexible \1% · shorten by up to \2 min'),
    (r'Hạn chót phải sau (.*)\.', r'The deadline must be after \1.'),
    (r'Chồng giờ với “(.*)”\. Hãy sửa giờ hoặc độ co dãn\.', r'Overlaps with “\1”. Adjust the time or flexibility.'),
    (r'Ước tính thiếu (\d+) phút trong phần tuần còn lại\.', r'Estimated shortfall of \1 minutes in the remaining week.'),
    (r'Nhập số nguyên từ (\d+) đến (\d+)\.', r'Enter an integer from \1 to \2.'),
    (r'Dòng (\d+): thừa ô; đặt ô chứa dấu phẩy trong dấu nháy kép\.', r'Row \1: extra cells; put cells containing commas in double quotes.'),
    (r'File JSON hỏng đã được giữ lại với tên (.*)', r'The damaged JSON file was retained as \1'),
    (r'Việc ngủ cũ “(.*)” được giữ như việc thường; bạn có thể xóa nếu trùng giờ ngủ trong Thiết lập chung\.', r'Legacy sleep task “\1” was retained as a regular task; you can delete it if it duplicates the general sleep settings.'),
    (r'Không đọc được bản ghi: (.*)', r'Unable to read record: \1'),
    (r'Thiếu danh sách (.*)', r'Missing list: \1'),
]


def language():
    return st.session_state.get('ui_language', 'vi')


def tr(value, lang=None):
    if (lang or language()) != 'en' or not isinstance(value, str):
        return value
    if value in EN:
        return EN[value]
    for pattern, replacement in PATTERNS:
        if re.fullmatch(pattern, value, flags=re.DOTALL):
            return re.sub(pattern, replacement, value, flags=re.DOTALL)
    prefix = 'Thiết lập file không hợp lệ; bảo vệ file gốc: '
    if value.startswith(prefix):
        return 'Invalid file settings; the original file is protected: ' + tr(value[len(prefix):], 'en')
    return value


def weekday_labels(lang=None):
    return ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] if (lang or language()) == 'en' else ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN']
