import json, os
from pathlib import Path
from datetime import datetime
from ..domain.models import *
from ..domain.validation import ValidationService
from ..application.mapper import TaskFactory
from ..application.parsers import DateTimeParser

class TaskRepository:
    def save(self,data,now_override):raise NotImplementedError
class InMemoryRepository(TaskRepository):
    def save(self,data,now_override):self.data=data
class JsonFileRepository(TaskRepository):
    def __init__(self,path):self.path=Path(path);self.blocked=False
    def save(self,data,now_override):
        if self.blocked:raise ValueError('File không tương thích đang được bảo vệ; chọn nơi lưu khác.')
        from ..application.mapper import hh
        payload={'schema_version':2,'saved_at':datetime.now().isoformat(timespec='seconds'),'settings':{'week_start':data.window.week_start.isoformat(),'sleep':{'start':hh(data.window.sleep.start),'end':hh(data.window.sleep.end)}},'fixed_tasks':[TaskFactory.to_dict(t) for t in data.fixed_tasks],'deadline_tasks':[TaskFactory.to_dict(t) for t in data.deadline_tasks]}
        self.path.parent.mkdir(parents=True,exist_ok=True)
        tmp=self.path.with_suffix('.tmp')
        with tmp.open('w',encoding='utf-8') as f:json.dump(payload,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
        os.replace(tmp,self.path)
    def load(self,default):
        notes=[]
        if not self.path.exists():return default,None,notes
        try:payload=json.loads(self.path.read_text(encoding='utf-8-sig'))
        except (ValueError,UnicodeError):
            target=self.path.with_name(f'schedule_input_draft.corrupt.{datetime.now():%Y%m%d%H%M%S%f}.json');self.path.rename(target)
            return default,None,['File JSON hỏng đã được giữ lại với tên '+target.name]
        if not isinstance(payload,dict) or payload.get('schema_version') not in (1,2):
            self.blocked=True;return default,None,['Phiên bản file không được hỗ trợ. File gốc được bảo vệ, chưa cho phép ghi đè.']
        try:
            s=payload['settings']; override=None
            if payload['schema_version']==1:
                import shutil
                backup=self.path.with_name(self.path.stem+'.v1.bak.json')
                if not backup.exists():shutil.copy2(self.path,backup)
                notes.append('Đã đọc dữ liệu cũ: importance 1–3 → 1, 4–7 → 2, 8–10 → 3. Đã giữ bản sao v1; giờ hiện tại và giờ ngủ trong Thiết lập chung được áp dụng.')
            week=DateTimeParser.day(s['week_start'])
            if week.weekday()!=0:raise ValueError('Tuần phải bắt đầu Thứ Hai.')
            sleep=SleepWindow(DateTimeParser.time(s['sleep']['start']),DateTimeParser.time(s['sleep']['end'],True));TimeRange(sleep.start,sleep.end)
            data=ScheduleInput(PlanningWindow(week,override or datetime.now(),sleep))
            for fixed,key in ((True,'fixed_tasks'),(False,'deadline_tasks')):
                if not isinstance(payload.get(key),list):raise ValueError('Thiếu danh sách '+key)
                for raw in payload[key]:
                    try:
                        raw=dict(raw)
                        if payload['schema_version']==1 and not fixed:
                            n=raw.get('importance',5)
                            if type(n) is not int or not 1<=n<=10:raise ValueError('importance không hợp lệ')
                            raw['importance']=1 if n<=3 else 2 if n<=7 else 3
                        if fixed and raw.get('is_sleep'):notes.append('Việc ngủ cũ “'+str(raw.get('name',''))+'” được giữ như việc thường; bạn có thể xóa nếu trùng giờ ngủ trong Thiết lập chung.')
                        t,r=TaskFactory.from_dict(raw,fixed)
                    except (TypeError,AttributeError,ValueError):t=None
                    if t is None:notes.append('Không đọc được bản ghi: '+str(raw));continue
                    if t.id in data._tasks:
                        from dataclasses import replace
                        t=replace(t,id=uid(fixed));notes.append('ID trùng: đã cấp ID mới.')
                    data.add(t)
            return data,override,notes
        except (KeyError,ValueError,TypeError) as ex:
            self.blocked=True;return default,None,['Thiết lập file không hợp lệ; bảo vệ file gốc: '+str(ex)]
