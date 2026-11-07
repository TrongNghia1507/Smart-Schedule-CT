from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from uuid import uuid4

class TaskKind(str, Enum):
    ASAP='asap'; HARD='hard'; SOFT='soft'
class FocusLevel(str, Enum):
    HIGH='high'; LOW='low'
class Weekday(str, Enum):
    MON='mon'; TUE='tue'; WED='wed'; THU='thu'; FRI='fri'; SAT='sat'; SUN='sun'
class Severity(str, Enum):
    ERROR='Error'; WARNING='Warning'; INFO='Info'

def uid(fixed=False): return ('ft_' if fixed else 'dt_')+uuid4().hex[:8]

@dataclass(frozen=True)
class TimeRange:
    # Minutes since midnight allow the end-of-day sentinel 1440 (24:00).
    start: int
    end: int
    def __post_init__(self):
        if not (0<=self.start<1440 and 0<=self.end<=1440) or self.start==self.end:
            raise ValueError('Giờ phải hợp lệ và bắt đầu khác kết thúc.')
    def crosses_midnight(self): return self.end<self.start
    def duration_min(self): return (self.end-self.start) if self.end>self.start else 1440-self.start+self.end
    def overlaps(self, other):
        a=self.start; b=a+self.duration_min()
        return any(max(a,other.start+k)<min(b,other.start+k+other.duration_min()) for k in (-1440,0,1440))

@dataclass(frozen=True)
class RepeatRule:
    days: frozenset[Weekday]=frozenset()
    one_off_date: date|None=None
    def __post_init__(self):
        if bool(self.days)==bool(self.one_off_date): raise ValueError('Chọn thứ hoặc ngày diễn ra, không chọn cả hai.')
    def is_one_off(self): return self.one_off_date is not None
    def label(self): return 'Một lần: '+self.one_off_date.strftime('%d/%m/%Y') if self.is_one_off() else ', '.join(['T2','T3','T4','T5','T6','T7','CN'][i] for i,d in enumerate(Weekday) if d in self.days)

@dataclass(frozen=True)
class ChunkPolicy:
    min_min:int; max_min:int
    def __post_init__(self):
        if self.min_min<=0 or self.max_min<self.min_min: raise ValueError('Chunk phải dương, min không vượt max.')
    def effective_max(self,remaining): return min(self.max_min,remaining)
    def can_split(self,remaining): return remaining>=2*self.min_min
    def max_chunks(self,remaining): return max(1,remaining//self.min_min)
@dataclass(frozen=True)
class BufferPolicy:
    minutes:int=15
    def __post_init__(self):
        if not 0<=self.minutes<=60 or self.minutes%5: raise ValueError('Buffer từ 0–60, chia hết cho 5.')
    def extra_minutes(self): return self.minutes
@dataclass(frozen=True)
class Flexibility:
    min_min:int; full_min:int
    def is_rigid(self): return self.min_min==self.full_min
    def rigidity_pct(self): return 100*self.min_min/self.full_min
    def shrinkable_min(self): return self.full_min-self.min_min
@dataclass(frozen=True)
class SleepWindow:
    start:int=1380; end:int=300
    def bands(self,day):
        r=TimeRange(self.start,self.end); t=datetime.combine(day,datetime.min.time())
        if r.crosses_midnight(): return ((t,t+timedelta(minutes=self.end)),(t+timedelta(minutes=self.start),t+timedelta(days=1)))
        return ((t+timedelta(minutes=self.start),t+timedelta(minutes=self.end)),)
@dataclass(frozen=True)
class PlanningWindow:
    week_start:date
    now:datetime
    sleep:SleepWindow=SleepWindow()
    def week_end(self): return self.week_start+timedelta(days=6)
    def contains(self,value): return self.week_start<=value.date()<=self.week_end()
@dataclass(frozen=True)
class Task:
    id:str; name:str
@dataclass(frozen=True)
class DeadlineTask(Task):
    kind:TaskKind; importance:int; deadline:datetime; remaining_min:int; focus:FocusLevel
    buffer:BufferPolicy; earliest_start:datetime|None; chunk:ChunkPolicy
    def effective_window(self,now): return max(now,self.earliest_start or now),self.deadline
    def can_split(self): return self.chunk.can_split(self.remaining_min)
@dataclass(frozen=True)
class FixedTask(Task):
    repeat:RepeatRule; time_range:TimeRange; is_flexible:bool; flexibility:Flexibility; is_sleep:bool=False
    @property
    def duration_min(self): return self.time_range.duration_min()
    def occurrences(self,week_start):
        left=datetime.combine(week_start,datetime.min.time()); right=left+timedelta(days=7)
        result=[]
        for offset in range(-1,7):
            d=week_start+timedelta(days=offset)
            if (self.repeat.one_off_date==d) if self.repeat.is_one_off() else (list(Weekday)[d.weekday()] in self.repeat.days):
                start=datetime.combine(d,datetime.min.time())+timedelta(minutes=self.time_range.start)
                end=start+timedelta(minutes=self.duration_min)
                if start<right and end>left: result.append((start,end))
        return tuple(result)
@dataclass(frozen=True)
class InputSnapshot:
    # Canonical serialized payload makes nested content immutable too.
    payload:str
    schema_version:int=2
    def to_json(self): return self.payload
    def to_dict(self):
        import json
        return json.loads(self.payload)
@dataclass
class ScheduleInput:
    window:PlanningWindow
    _tasks:dict=field(default_factory=dict,repr=False)
    @property
    def fixed_tasks(self): return tuple(t for t in self._tasks.values() if isinstance(t,FixedTask))
    @property
    def deadline_tasks(self): return tuple(t for t in self._tasks.values() if isinstance(t,DeadlineTask))
    def add(self,task):
        if task.id in self._tasks: raise ValueError('ID trùng.')
        self._tasks[task.id]=task
    def update(self,task):
        if task.id not in self._tasks: raise KeyError(task.id)
        self._tasks[task.id]=task
    def remove(self,id): return self._tasks.pop(id)
    def get_by_id(self,id): return self._tasks[id]
