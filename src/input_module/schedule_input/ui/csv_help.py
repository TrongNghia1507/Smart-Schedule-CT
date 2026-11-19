"""Unified CSV help and a downloadable example using the selected planning week."""
import csv
import io
import streamlit as st


def example_csv(window):
    stream=io.StringIO(newline='')
    writer=csv.writer(stream)
    writer.writerow(['task_type','name','repeat','start','end','prep_min','after_min',
                     'mandatory','deadline','remaining_min'])
    writer.writerow(['fixed','Học trên lớp','T2,T4','08:00','10:00',15,10,'','',''])
    writer.writerow(['deadline','Làm bài tập','','','','','','Có',
                     window.week_end().strftime('%d/%m/%Y')+' 23:59',90])
    return stream.getvalue()

def render_csv_help(window,lang='vi'):
    en=lang=='en'
    with st.expander('ⓘ Input guide' if en else 'ⓘ Hướng dẫn input',expanded=False):
        st.markdown(
            'Use **one UTF-8 CSV file** for both task types, with a header row and comma separators. '
            'Set `task_type` to **fixed** or **deadline** on each row. Leave unrelated columns blank. '
            'Import adds tasks to your current list.' if en else
            'Dùng **một file CSV UTF-8** cho cả hai loại việc, có dòng tiêu đề và phân tách bằng dấu phẩy. '
            'Mỗi dòng điền `task_type` là **fixed** hoặc **deadline**. Cột không áp dụng để trống. '
            'Nhập CSV sẽ thêm việc vào danh sách hiện tại.')
        if en:
            st.markdown('''| Type | Required fields | Optional fields and defaults |
| --- | --- | --- |
| Both | `task_type`, `name` | |
| `fixed` | `start`, `end`; `repeat` or `one_off_date` | `prep_min`: 0–90 (0); `after_min`: 0–60 (0); `is_flexible`: Yes/No (No); `min_duration_min`: full duration |
| `deadline` | `deadline`; `remaining_min` | `mandatory`: Yes/No (Yes); `importance`: 1–3 (2); `focus`: high/low (high); `buffer_min`: 0–60, multiple of 5 (15); `earliest_start`; `chunk_min`, `chunk_max`: high 45/90, low 30/60 |''')
        else:
            st.markdown('''| Loại | Cột bắt buộc | Cột tùy chọn và mặc định |
| --- | --- | --- |
| Cả hai | `task_type`, `name` | |
| `fixed` | `start`, `end`; `repeat` hoặc `one_off_date` | `prep_min`: 0–90 (0); `after_min`: 0–60 (0); `is_flexible`: Có/Không (Không); `min_duration_min`: toàn bộ thời lượng |
| `deadline` | `deadline`; `remaining_min` | `mandatory`: Có/Không (Có); `importance`: 1–3 (2); `focus`: high/low (high); `buffer_min`: 0–60, chia hết cho 5 (15); `earliest_start`; `chunk_min`, `chunk_max`: high 45/90, low 30/60 |''')
        st.markdown(
            'Times: `HH:mm` (`end` also accepts `24:00`). Dates: `dd/mm/yyyy`. Deadlines and earliest starts: '
            '`dd/mm/yyyy HH:mm`. Repeat: `T2->CN` or `"T2,T4"`; quote any cell containing a comma. '
            'For a one-off task, leave `repeat` blank and fill `one_off_date`. Duration values use minutes. '
            'There is no free-deadline column: enter Sunday 23:59 in `deadline`.' if en else
            'Giờ: `HH:mm` (`end` cho phép `24:00`). Ngày: `dd/mm/yyyy`. Hạn chót và bắt đầu sớm nhất: '
            '`dd/mm/yyyy HH:mm`. Lặp: `T2->CN` hoặc `"T2,T4"`; ô có dấu phẩy phải đặt trong dấu nháy kép. '
            'Việc một lần: để trống `repeat`, điền `one_off_date`. Thời lượng tính bằng phút. '
            'Không có cột free deadline: điền 23:59 Chủ nhật vào `deadline`.')
        st.caption('Example for the selected week (adjust dates before importing):' if en else
                   'Ví dụ theo tuần đang lập lịch (điều chỉnh ngày trước khi nhập):')
        example=example_csv(window)
        st.code(example,language='csv')
        st.download_button('Download example CSV' if en else 'Tải CSV mẫu',
                           example.encode('utf-8-sig'),'tasks_example.csv','text/csv',key='csv_example')
