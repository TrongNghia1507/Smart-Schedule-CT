from dataclasses import dataclass
from ..domain.models import *
from ..domain.validation import *
from .parsers import *

RawRow=dict
class DefaultsProvider:
    @staticmethod
    def chunk(focus):return (45,90) if focus=='high' else (30,60)
def hh(n):return f'{n//60:02}:{n%60:02}'
class TaskFactory:
    @staticmethod
    def from_raw(raw,fixed=False):
        r=ValidationReport(); id=raw.get('id') or uid(fixed)
        def read(k,fn,code,default=None):
            v=raw.get(k)
            if v is None or str(v).strip()=='':v=default
            try:return fn(v)
            except (ValueError,TypeError,KeyError) as ex:r.add(code,Severity.ERROR,k,id,str(ex));return None
        def integer(v):
            if isinstance(v,bool):raise ValueError('Cần số nguyên.')
            return DurationParser.parse(v)
        def bounded(v,lo,hi):
            n=integer(v)
            if not lo<=n<=hi:raise ValueError(f'Nhập số nguyên từ {lo} đến {hi}.')
            return n
        name=str(raw.get('name') or '').strip()
        if not name or len(name)>100:r.add('V01',Severity.ERROR,'name',id,'Tên bắt buộc, tối đa 100 ký tự.')
        if fixed:
            days=read('repeat',RepeatParser.parse,'F01','')
            day=read('one_off_date',DateTimeParser.day,'F01') if not days else None
            start=read('start',DateTimeParser.time,'F02'); end=read('end',lambda v:DateTimeParser.time(v,True),'F02')
            flex=read('is_flexible',BoolParser.parse,'F03','Không'); sleep=False
            tr=None
            if start is not None and end is not None:
                try:tr=TimeRange(start,end)
                except ValueError as ex:r.add('F02',Severity.ERROR,'end',id,str(ex))
            duration=tr.duration_min() if tr else 1440
            minimum=read('min_duration_min',lambda v:bounded(v,1,duration),'F03',duration) if flex else duration
            if r.has_errors():return None,r
            return FixedTask(id,name,RepeatRule(days,day),tr,flex,Flexibility(minimum,duration),sleep),r
        kind=read('kind',TaskKind,'V02'); focus=read('focus',FocusLevel,'V02','high')
        importance=read('importance',lambda v:bounded(v,1,3),'V03',2)
        deadline=read('deadline',DateTimeParser.parse,'V04')
        remaining=read('remaining_min',lambda v:bounded(v,1,10**9),'V08')
        early=read('earliest_start',DateTimeParser.parse,'V09') if raw.get('earliest_start') else None
        buffer=read('buffer_min',lambda v:BufferPolicy(integer(v)),'V17',15)
        defaults=DefaultsProvider.chunk(focus)
        mn=read('chunk_min',lambda v:bounded(v,1,10**9),'V11',defaults[0]); mx=read('chunk_max',lambda v:bounded(v,1,10**9),'V11',defaults[1])
        if mn and mx and mn>mx:r.add('V11',Severity.ERROR,'chunk_max',id,'Chunk max phải lớn hơn hoặc bằng min.')
        if r.has_errors():return None,r
        return DeadlineTask(id,name,kind,importance,deadline,remaining,focus,buffer,early,ChunkPolicy(mn,mx)),r
    @staticmethod
    def to_dict(t):
        row={'id':t.id,'name':t.name}
        if isinstance(t,FixedTask):
            row.update(repeat_days=[d.value for d in Weekday if d in t.repeat.days],one_off_date=t.repeat.one_off_date.isoformat() if t.repeat.one_off_date else None,start=hh(t.time_range.start),end=hh(t.time_range.end),is_flexible=t.is_flexible,min_duration_min=t.flexibility.min_min if t.is_flexible else None)
        else:
            row.update(kind=t.kind.value,importance=t.importance,deadline=t.deadline.isoformat(timespec='minutes'),remaining_min=t.remaining_min,focus=t.focus.value,buffer_min=t.buffer.minutes,earliest_start=t.earliest_start.isoformat(timespec='minutes') if t.earliest_start else None,chunk_min=t.chunk.min_min,chunk_max=t.chunk.max_min)
        return row
    @staticmethod
    def to_row_view(t):
        row=TaskFactory.to_dict(t)
        if isinstance(t,FixedTask):row['repeat']=','.join(row.pop('repeat_days'))
        return {k:('' if v is None else ('Có' if v else 'Không') if isinstance(v,bool) else str(v)) for k,v in row.items()}
    @staticmethod
    def from_dict(row,fixed=False):
        raw=dict(row)
        if fixed:raw['repeat']=','.join(raw.pop('repeat_days',[]))
        return TaskFactory.from_raw(raw,fixed)

Mapper=TaskFactory
