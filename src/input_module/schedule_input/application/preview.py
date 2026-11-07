import json
from dataclasses import dataclass
from datetime import datetime,timedelta
from ..domain.models import *
from ..domain.validation import sleep_bands,ValidationService,free_minutes
from .mapper import TaskFactory

@dataclass(frozen=True)
class CalendarEvent:
    task_id:str; title:str; start:datetime; end:datetime; segment_index:int
@dataclass(frozen=True)
class BlockedBand:
    start:datetime; end:datetime; reason:str='Giờ ngủ mặc định'
@dataclass(frozen=True)
class PreviewModel:
    events:tuple; bands:tuple; free_minutes:int
class CalendarProjector:
    def project(self,data):
        left=datetime.combine(data.window.week_start,datetime.min.time()); right=left+timedelta(days=7); events=[]
        for t in data.fixed_tasks:
            for a,b in t.occurrences(data.window.week_start):
                a=max(a,left); b=min(b,right); index=0
                while a<b:
                    stop=min(b,datetime.combine(a.date()+timedelta(days=1),datetime.min.time()))
                    events.append(CalendarEvent(t.id,t.name,a,stop,index)); a=stop; index+=1
        return tuple(events),tuple(BlockedBand(a,b) for a,b in sleep_bands(data))
class PreviewService:
    def build(self,data):
        events,bands=CalendarProjector().project(data)
        return PreviewModel(events,bands,free_minutes(data))
class SnapshotBuilder:
    def build(self,data):
        report=ValidationService().validate_all(data)
        if report.has_errors():raise ValueError('Còn lỗi; chưa thể bàn giao.')
        w=data.window
        payload={'schema_version':2,'created_at':datetime.now().isoformat(timespec='seconds'),'window':{'week_start':w.week_start.isoformat(),'week_end':w.week_end().isoformat(),'now':w.now.isoformat(timespec='minutes'),'sleep':{'start':f'{w.sleep.start//60:02}:{w.sleep.start%60:02}','end':f'{w.sleep.end//60:02}:{w.sleep.end%60:02}','is_default':True,'default_bands':[{'start':a.isoformat(),'end':b.isoformat()} for a,b in sleep_bands(data)]}},'fixed_tasks':[],'deadline_tasks':[]}
        for t in data.fixed_tasks:
            row=TaskFactory.to_dict(t); row.update(duration_min=t.duration_min,occurrences=[{'date':a.date().isoformat(),'start':a.isoformat(),'end':b.isoformat()} for a,b in t.occurrences(w.week_start)]);payload['fixed_tasks'].append(row)
        for t in data.deadline_tasks:
            row=TaskFactory.to_dict(t); a,b=t.effective_window(w.now)
            row.update(effective_window={'start':a.isoformat(),'end':b.isoformat()},effective_chunk={'min':min(t.chunk.min_min,t.remaining_min),'max':t.chunk.effective_max(t.remaining_min)},can_split=t.can_split());payload['deadline_tasks'].append(row)
        return InputSnapshot(json.dumps(payload,ensure_ascii=False,indent=2))
