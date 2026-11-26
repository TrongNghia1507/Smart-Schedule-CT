# Scheduling

Bộ xếp lịch công việc dùng OR-Tools CP-SAT. Chương trình chọn task, chia thành các phiên làm việc (chunk), tránh lịch cố định và tối ưu theo mục tiêu có trọng số.

## 1. Cấu trúc và tác dụng từng file

```text
src/scheduling_algorithm/
├── main.py
├── parseOutput.py
├── core_algorithm/
│   ├── models.py
│   ├── context.py
│   ├── parseInput.py
│   ├── history.py
│   ├── criteria.py
│   └── solve.py
└── history/
    └── schedule_history.json
```

| File | Tác dụng |
| --- | --- |
| `main.py` | Điểm chạy chương trình: đọc tham số, gọi parser và solver, in bảng, lưu JSON. |
| `core_algorithm/models.py` | Khai báo `Config`, `Task`, `FixedTask`, `SolveResult` và phép đổi phút/slot. |
| `core_algorithm/context.py` | Chứa `Chunk` và `Ctx`, tập hợp biến để solver và các mục tiêu dùng chung. |
| `core_algorithm/parseInput.py` | Đọc JSON, chuyển thời gian, làm tròn theo slot, tạo các đối tượng đầu vào. |
| `core_algorithm/criteria.py` | Đăng ký và tính điểm các mục tiêu tối ưu. |
| `core_algorithm/solve.py` | Tạo biến, ràng buộc, mục tiêu; chạy CP-SAT và lấy lịch kết quả. |
| `parseOutput.py` | Chuyển `SolveResult` thành chuỗi JSON. Đổi slot thành phút tuyệt đối; không validate và không in bảng. |
| `core_algorithm/history.py` | Đọc và lưu lịch người dùng đã chọn. |
| `examples/solver/input_test.json` | Dữ liệu thử gồm 7 task, lịch cố định và task không kịp deadline. |
| `examples/solver/input_test_result.json` | Kết quả mẫu để đối chiếu. File không tự cập nhật khi chạy ví dụ bên dưới. |

Luồng chạy: **JSON input → parseInput → solve → SolveResult → parseOutput → JSON output**. `main.py` điều phối luồng này và in bảng riêng.

## 2. Cài môi trường

Mở PowerShell tại thư mục gốc của repo. Nếu chỉ muốn chạy bộ giải từ terminal, cài dự án vào môi trường Python riêng.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Nếu đã cài phụ thuộc theo README, dùng môi trường `.venv` đã tạo.

## 3. Chạy chương trình

Chạy từ thư mục gốc của repo.

```powershell
.\.venv\Scripts\python.exe -m scheduling_algorithm.main examples/solver/input_test.json -o schedule_result.json
```

Kết quả gồm bảng trên terminal và file JSON ở đường dẫn `-o`. Thư mục output phải tồn tại; file output cùng tên sẽ bị ghi đè.

Nếu không truyền `-o`, chương trình lưu cạnh file input với tên `<tên_input>_result.json`.

```powershell
.\.venv\Scripts\python.exe -m scheduling_algorithm.main --help
```

`OPTIMAL` là đã tìm và chứng minh nghiệm tối ưu; `FEASIBLE` là có nghiệm nhưng chưa chứng minh tối ưu. `INFEASIBLE` là không có nghiệm; `UNKNOWN` là chưa có kết luận; `MODEL_INVALID` là mô hình không hợp lệ. Chương trình trả mã thoát 0 khi có nghiệm, 1 khi không có nghiệm để hiển thị.

## 4. Input mẫu

Đây là ví dụ nhỏ, có thể lưu thành `examples/solver/example.json`.

```json
{
  "config": {
    "day_start": "08:00",
    "day_end": "17:00",
    "num_days": 1,
    "time_limit": 10,
    "slot_minutes": 5,
    "break_minutes": 10,
    "objective": {
      "max_count": 10,
      "early_finish": 5,
      "fewer_pieces": 1
    }
  },
  "tasks": [
    {
      "id": 1,
      "name": "Lam bai tap",
      "duration": 120,
      "priority": 3,
      "deadline": {"day": 0, "time": "12:00"},
      "splittable": true,
      "min_chunk": 30,
      "max_chunk": 60
    }
  ],
  "fixed_tasks": [
    {
      "name": "Nghi trua",
      "days": [0],
      "start": "12:00",
      "end": "13:00"
    }
  ]
}
```

### Quy ước đầu vào

- Thời lượng, `min_chunk`, `max_chunk`, `break_minutes` tính bằng phút. `time_limit` tính bằng giây.
- Ngày trong input đánh số từ **0**. Bảng terminal hiển thị từ **1**.
- `duration` là tổng thời gian làm task, không bao gồm nghỉ. Task được chọn phải được xếp đủ thời lượng.
- `splittable=false`: task chỉ có một chunk. `splittable=true`: mỗi chunk được dùng nằm trong giới hạn min/max.
- `break_minutes` là khoảng cách tối thiểu giữa mọi chunk task, kể cả khác task. Không thêm break vào lịch cố định; lịch cố định có thể nằm trong khoảng cách này.
- Bỏ `deadline` thì task không có deadline riêng. Bỏ `fixed_tasks` thì không có lịch cố định. Bỏ `days` trong một lịch cố định thì lịch đó lặp mỗi ngày.
- Input được giả định đã sạch: ID duy nhất, thời lượng dương, các giới hạn hợp lệ, priority không âm, lịch cố định không chồng nhau. Dùng `slot_minutes` chia hết 1440 và giờ làm việc khớp lưới slot.
- Parser làm tròn thời lượng lên, deadline xuống; break được làm tròn lên theo slot. Bên validate cần dùng cùng quy ước.

| Cấu hình tùy chọn | Mặc định |
| --- | --- |
| `num_days` | 7 |
| `time_limit` | 10 giây |
| `slot_minutes` | 5 phút |
| `break_minutes` | 10 phút |
| `priority` của task | 1 |
| `splittable` | false |
| `min_chunk` khi được chia | 30 phút, giới hạn không vượt duration |
| `max_chunk` khi được chia | duration |

### Mục tiêu

| Tên | Ý nghĩa |
| --- | --- |
| `max_priority` | Tối đa tổng priority của task được chọn. |
| `max_count` | Tối đa số task được chọn. |
| `early_finish` | Ưu tiên hoàn thành sớm, nhân priority; task bị bỏ nhận điểm 0. |
| `fewer_pieces` | Giảm tổng số chunk được dùng. |

Chỉ các trọng số dương được sử dụng. Không nhập mục tiêu, nhập `{}`, hoặc mọi trọng số đều không dương thì mặc định `max_priority: 1`. Khi có mục tiêu được chọn, chúng cạnh tranh bằng tổng điểm có trọng số; `max_priority` không tự động có ưu tiên tuyệt đối.

Điểm được chuẩn hóa gần đúng bằng hệ số nguyên. `fewer_pieces` dùng riêng có thể chọn lịch rỗng, nên kết hợp mục tiêu chọn việc nếu muốn xếp task.

## 5. Output mẫu

Ví dụ một kết quả hợp lệ cho input nhỏ ở trên; `solve_time` chỉ để minh họa, thay đổi theo lần chạy:

```json
{
  "status": "OPTIMAL",
  "solve_time": 0.01,
  "unscheduled_task_ids": [],
  "time_unit": "minutes",
  "time_origin": "day_0_00:00",
  "tasks": [
    {
      "task_id": 1,
      "chunks": [
        {"start": 480, "end": 540},
        {"start": 550, "end": 610}
      ]
    }
  ]
}
```

Hai phiên tương ứng 08:00–09:00 và 09:10–10:10, cách nhau 10 phút.

- `start`, `end` là **phút tuyệt đối từ 00:00 ngày 0**, không phải slot hay chuỗi giờ. Ví dụ 08:00 ngày 1 là `1440 + 480 = 1920`.
- Khoảng làm việc được hiểu là `[start, end)`, thời lượng bằng `end - start`.
- `tasks` chứa task được chọn. `unscheduled_task_ids` chứa ID các task không được chọn, theo thứ tự input; nếu xếp đủ task thì là `[]`. JSON không chứa lịch cố định hay các khoảng nghỉ.
- Không có điểm objective trong JSON và bảng terminal.
- Khi không tìm được nghiệm (`UNKNOWN`, `INFEASIBLE`, `MODEL_INVALID`), `tasks` là `[]` và `unscheduled_task_ids` là `null`. Chưa có lịch để kết luận task nào được chọn; phải đọc `status`. Với nghiệm hợp lệ nhưng không chọn task nào, `unscheduled_task_ids` chứa toàn bộ ID input.
- Người phụ trách validate cần **cả JSON input và output**, cùng các giá trị mặc định và quy tắc làm tròn của chương trình.

## 6. Lỗi thường gặp

- Nếu Python không tìm thấy `scheduling_algorithm` hoặc `ortools`, chạy lại lệnh cài đặt ở mục 2 bằng Python trong `.venv`.
- Nếu không tìm thấy `.venv\Scripts\python.exe`, kiểm tra đã tạo `.venv` từ thư mục gốc của repo.
