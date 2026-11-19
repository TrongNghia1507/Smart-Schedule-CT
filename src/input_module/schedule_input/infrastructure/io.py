import csv,io,json
from pathlib import Path
from datetime import datetime,date
from ..application.mapper import TaskFactory
from ..domain.models import *

FIELDS={True:['name','repeat','start','end','is_flexible','min_duration_min','one_off_date','prep_min','after_min','removable_when_busy'],False:['name','mandatory','importance','deadline','remaining_min','focus','buffer_min','earliest_start','chunk_min','chunk_max']}
ALIASES={'Tên':'name','Tên công việc (name)':'name','Bắt buộc (mandatory)':'mandatory','Quan trọng (is_important)':'importance','Hạn chót (deadline)':'deadline','Thời lượng (remaining_min)':'remaining_min','Tập trung (focus)':'focus','Buffer 15p':'buffer_min','Bắt đầu sớm nhất (earliest_start)':'earliest_start','Chunk min':'chunk_min','Chunk max':'chunk_max','Lặp lại':'repeat','Giờ bắt đầu':'start','Giờ kết thúc':'end','Có thể chia ko (OPTIONAL)':'is_flexible','Thời gian co dãn tối thiểu (OPTIONAL)':'min_duration_min','Xóa được khi bận':'removable_when_busy'}
COMBINED_FIELDS=['task_type',*dict.fromkeys(FIELDS[True]+FIELDS[False])]
def norm(s):return ' '.join(s.strip().casefold().split())
class CsvXlsxGateway:
    # XLSX is intentionally a deferred Could feature; CSV is the supported gateway.
    def read_mixed_rows(self,content):
        mapping={norm(x):x for x in COMBINED_FIELDS}
        mapping.update({norm(k):v for k,v in ALIASES.items()})
        reader=csv.DictReader(io.StringIO(content.decode('utf-8-sig')))
        headers=reader.fieldnames or []
        canonical=[mapping.get(norm(h),norm(h)) for h in headers]
        if 'task_type' not in canonical or 'name' not in canonical:
            raise ValueError('CSV phải có cột task_type và name, phân tách bằng dấu phẩy.')
        if len(set(canonical))!=len(canonical):
            raise ValueError('CSV có tên cột trùng nhau.')
        rows=[];notes=[h for h in headers if norm(h) not in mapping]
        for i,row in enumerate(reader,2):
            if None in row:
                raise ValueError(f'Dòng {i}: thừa ô; đặt ô chứa dấu phẩy trong dấu nháy kép.')
            if not any((v or '').strip() for v in row.values()):continue
            out={mapping[norm(k)]:(v or '').strip() for k,v in row.items() if norm(k) in mapping}
            out['task_type']=out['task_type'].casefold()
            if 'buffer_min' in out and norm(out['buffer_min']) in ('có','không'):
                out['buffer_min']='15' if norm(out['buffer_min'])=='có' else '0'
            rows.append((i,out))
        return rows,notes

    def write_mixed_rows(self,data):
        stream=io.StringIO(newline='')
        writer=csv.DictWriter(stream,fieldnames=COMBINED_FIELDS)
        writer.writeheader()
        for fixed in (True,False):
            # Reuse the same date/time formatting as the individual table export.
            rows=csv.DictReader(io.StringIO(self.write_rows(data,fixed).decode('utf-8-sig')))
            for row in rows:writer.writerow(dict(task_type='fixed' if fixed else 'deadline',**row))
        return stream.getvalue().encode('utf-8-sig')

    def read_rows(self,content,fixed):
        mapping={norm(x):x for x in FIELDS[fixed]};mapping.update({norm(k):v for k,v in ALIASES.items()})
        rows=[];notes=[]
        reader=csv.DictReader(io.StringIO(content.decode('utf-8-sig')))
        for i,row in enumerate(reader,2):
            out={}
            for key,value in row.items():
                if key is None:raise ValueError(f'Dòng {i}: thừa ô; đặt ô chứa dấu phẩy trong dấu nháy kép.')
                target=mapping.get(norm(key))
                if target in FIELDS[fixed]:out[target]=(value or '').strip()
                elif key not in notes:notes.append(key)
            if 'buffer_min' in out and norm(out['buffer_min']) in ('có','không'):out['buffer_min']='15' if norm(out['buffer_min'])=='có' else '0'
            rows.append((i,out))
        return rows,notes
    def write_rows(self,data,fixed):
        stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=FIELDS[fixed]);writer.writeheader()
        for task in data.fixed_tasks if fixed else data.deadline_tasks:
            row=TaskFactory.to_row_view(task);row.pop('id')
            if fixed:
                row['repeat']='' if task.repeat.is_one_off() else task.repeat.label()
                if task.repeat.one_off_date:row['one_off_date']=task.repeat.one_off_date.strftime('%d/%m/%Y')
            else:
                row['deadline']=task.deadline.strftime('%d/%m/%Y %H:%M')
                row['earliest_start']=task.earliest_start.strftime('%d/%m/%Y %H:%M') if task.earliest_start else ''
            writer.writerow(row)
        return stream.getvalue().encode('utf-8-sig')
class SampleDataProvider:
    def load(self):
        payload=json.loads(Path(__file__).with_name('sample.json').read_text(encoding='utf-8'))
        data=ScheduleInput(PlanningWindow(date(2026,10,19),datetime(2026,10,19,8)))
        for fixed,key in ((True,'fixed_tasks'),(False,'deadline_tasks')):
            for row in payload[key]:
                if not fixed:row["importance"]=1 if row["importance"]<=3 else 2 if row["importance"]<=7 else 3
                t,r=TaskFactory.from_dict(row,fixed)
                if r.has_errors():raise ValueError(r)
                data.add(t)
        return data

    def demo(self):
        from dataclasses import replace
        from datetime import timedelta
        data=self.load();now=datetime.now()
        week=now.date()-timedelta(days=now.weekday())+timedelta(days=7)
        shift=week-data.window.week_start
        for t in data.deadline_tasks:
            data.update(replace(t,deadline=t.deadline+shift,earliest_start=t.earliest_start+shift if t.earliest_start else None))
        data.window=PlanningWindow(week,now,data.window.sleep)
        return data
