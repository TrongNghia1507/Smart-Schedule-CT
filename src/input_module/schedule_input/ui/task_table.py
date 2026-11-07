from pathlib import Path
import streamlit.components.v1 as components
from ..application.mapper import TaskFactory
from .theme import PALETTES
from .i18n import tr,weekday_labels
from ..domain.models import Weekday

_table=components.declare_component('schedule_task_table',path=str(Path(__file__).parent/'table_component'))

def table_payload(tasks,fixed,report,lang='vi'):
    rows=[]
    for task in tasks:
        raw=TaskFactory.to_row_view(task)
        if fixed:
            raw['repeat']='' if task.repeat.is_one_off() else task.repeat.label()
            if len(task.repeat.days)==7:raw['repeat']='T2–CN'
            if not task.is_flexible:raw['min_duration_min']=str(task.duration_min)
            meta={'duration':f'{task.duration_min//60} giờ {task.duration_min%60:02}' if task.duration_min>=60 else f'{task.duration_min} phút','rigidity':f'Cứng 100%' if task.flexibility.is_rigid() else f'Co dãn {100-task.flexibility.rigidity_pct():g}% · rút tối đa {task.flexibility.shrinkable_min()} phút'}
        else:
            raw['deadline']=task.deadline.strftime('%d/%m/%Y %H:%M')
            raw['earliest_start']=task.earliest_start.strftime('%d/%m/%Y %H:%M') if task.earliest_start else ''
            meta={}
        if fixed:
            meta={k:tr(v,lang) for k,v in meta.items()}
            if lang=='en' and not task.repeat.is_one_off():
                raw['repeat']='Mon–Sun' if len(task.repeat.days)==7 else ', '.join(weekday_labels(lang)[i] for i,d in enumerate(Weekday) if d in task.repeat.days)
        issues=[{'field':i.field,'message':tr(i.message,lang),'severity':i.severity.value} for i in report.by_task(task.id)]
        rows.append({'raw':raw,'meta':meta,'issues':issues})
    return rows

def render_table(tasks,fixed,report,mode,revision,lang='vi'):
    return _table(rows=table_payload(tasks,fixed,report,lang),lang=lang,fixed=fixed,palette=PALETTES[mode],key=f'tasks_{fixed}_{revision}',default=None)
