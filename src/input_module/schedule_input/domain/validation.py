from dataclasses import dataclass, field
from datetime import datetime, timedelta
from .models import *

@dataclass(frozen=True)
class ValidationIssue:
    code:str; severity:Severity; field:str; task_id:str; message:str
@dataclass
class ValidationReport:
    issues:list=field(default_factory=list)
    def has_errors(self): return any(i.severity==Severity.ERROR for i in self.issues)
    def by_task(self,id): return [i for i in self.issues if i.task_id==id]
    def by_field(self,name): return [i for i in self.issues if i.field==name]
    def add(self,code,severity,field,id,msg): self.issues.append(ValidationIssue(code,severity,field,id,msg))

def sleep_bands(data):
    return tuple((a,b) for i in range(7) for a,b in data.window.sleep.bands(data.window.week_start+timedelta(days=i)) if a<b)

def overlap(a,b): return max(a[0],b[0])<min(a[1],b[1])
def free_minutes(data):
    left=max(data.window.now,datetime.combine(data.window.week_start,datetime.min.time()))
    right=datetime.combine(data.window.week_start+timedelta(days=7),datetime.min.time())
    if left>=right:return 0
    intervals=[(max(a,left),min(b,right)) for t in data.fixed_tasks for a,b in t.occurrences(data.window.week_start)]
    intervals += [(max(a,left),min(b,right)) for a,b in sleep_bands(data)]
    total=0; last=left
    for a,b in sorted((a,b) for a,b in intervals if a<b):
        if b>last: total+=(b-max(a,last)).total_seconds()/60; last=b
    return int((right-left).total_seconds()/60-total)

class ValidationRule:
    def check(self,task,context): raise NotImplementedError

class DeadlineRules(ValidationRule):
    def check(self,t,data):
        r=ValidationReport()
        def add(c,s,f,m):r.add(c,s,f,t.id,m)
        E=Severity.ERROR; W=Severity.WARNING; I=Severity.INFO
        if t.deadline<=data.window.now:add('V05',E,'deadline',f'Hạn chót phải sau {data.window.now:%d/%m/%Y %H:%M}.')
        if t.deadline.hour<6:add('V06',W,'deadline','Hạn chót rạng sáng; hãy kiểm tra lại giờ.')
        if not data.window.contains(t.deadline):add('V07',W,'deadline','Hạn chót ngoài tuần đang lập lịch.')
        if t.remaining_min%5:add('V08b',W,'remaining_min','Thời lượng không chia hết cho 5; cân nhắc làm tròn.')
        if t.earliest_start and t.earliest_start>=t.deadline:add('V09',E,'earliest_start','Bắt đầu sớm nhất phải trước hạn chót.')
        if t.earliest_start and t.earliest_start<data.window.now:add('V10',I,'earliest_start','Cửa sổ hiệu dụng được nâng lên mốc bây giờ.')
        if t.chunk.min_min>t.remaining_min:add('V12',W,'chunk_min','Dùng nguyên thời lượng làm một khối.')
        if t.chunk.max_min>t.remaining_min:add('V13',I,'chunk_max','Chunk max hiệu dụng được giới hạn bằng thời lượng.')
        if not t.can_split():add('V14',I,'chunk_min','Việc này sẽ được xếp liền 1 khối.')
        a,b=t.effective_window(data.window.now)
        if (b-a).total_seconds()/60<t.remaining_min+t.buffer.minutes:add('V15',W,'remaining_min','Khoảng khả dụng ngắn hơn thời lượng cộng nghỉ đệm.')
        if any(o.id!=t.id and o.name.casefold()==t.name.casefold() for o in data.deadline_tasks):add('V16',W,'name','Trùng tên với việc khác; kiểm tra có nhập trùng không.')
        return r.issues
class FixedRules(ValidationRule):
    def check(self,t,data):
        r=ValidationReport()
        if t.repeat.is_one_off() and not data.window.week_start<=t.repeat.one_off_date<=data.window.week_end():r.add('F06',Severity.WARNING,'one_off_date',t.id,'Ngày diễn ra ngoài tuần đang lập lịch.')
        if t.time_range.crosses_midnight():r.add('F07',Severity.INFO,'end',t.id,'Việc kéo sang hôm sau, lịch hiển thị thành các đoạn theo ngày.')
        if not t.is_sleep and any(overlap(a,b) for a in t.occurrences(data.window.week_start) for b in sleep_bands(data)):r.add('F05',Severity.INFO,'start',t.id,'Chạm giờ ngủ mặc định; kiểm tra lại giờ.')
        return r.issues
class ValidationService:
    def __init__(self):self.rules={DeadlineTask:DeadlineRules(),FixedTask:FixedRules()}
    def validate_task(self,t,ctx):return ValidationReport(self.rules[type(t)].check(t,ctx))
    def validate_all(self,data):
        r=ValidationReport()
        for t in (*data.fixed_tasks,*data.deadline_tasks):r.issues.extend(self.validate_task(t,data).issues)
        tasks=data.fixed_tasks
        for i,a in enumerate(tasks):
            for b in tasks[i+1:]:
                if any(overlap(x,y) for x in a.occurrences(data.window.week_start) for y in b.occurrences(data.window.week_start)):
                    rigid=a.flexibility.is_rigid() and b.flexibility.is_rigid()
                    for t,o in ((a,b),(b,a)):
                        r.add('F04',Severity.ERROR if rigid else Severity.WARNING,'start',t.id,f'Chồng giờ với “{o.name}”. Hãy sửa giờ hoặc độ co dãn.')
                        if a.is_sleep and b.is_sleep:r.add('F08',Severity.WARNING,'is_sleep',t.id,'Hai việc ngủ chồng nhau; kiểm tra nhập trùng.')
        if not tasks and not data.deadline_tasks:r.add('G02',Severity.ERROR,'', '', 'Hãy nhập ít nhất một việc.')
        for group in (tasks,data.deadline_tasks):
            if len(group)>100:r.add('G03',Severity.WARNING,'','','Trên 100 việc một loại; hiệu năng có thể giảm.')
        need=sum(t.remaining_min+t.buffer.minutes for t in data.deadline_tasks)
        free=free_minutes(data)
        if need>free:r.add('G01',Severity.WARNING,'','',f'Ước tính thiếu {need-free} phút trong phần tuần còn lại.')
        return r
