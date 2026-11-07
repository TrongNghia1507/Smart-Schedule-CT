from streamlit_calendar import calendar
from .theme import PALETTES

def initial_scroll_time(window):
    if window.contains(window.now):
        minutes=max(0,window.now.hour*60+window.now.minute-60)
        return f'{minutes//60:02}:{minutes%60:02}:00'
    return '06:00:00'

def calendar_events(data,model,report,mode='light'):
    p=PALETTES[mode]
    conflicts={i.task_id for i in report.issues if i.code=='F04'}
    flexible={t.id for t in data.fixed_tasks if not t.flexibility.is_rigid()}
    events=[{'id':f'{e.task_id}@{e.start.isoformat()}#{e.segment_index}','extendedProps':{'task_id':e.task_id},'title':e.title+(' ↔' if e.task_id in flexible else ''),'start':e.start.isoformat(),'end':e.end.isoformat(),'backgroundColor':p['event'],'borderColor':'#e4a83a' if e.task_id in conflicts else p['event'],'textColor':'#ffffff','classNames':['short-event'] if (e.end-e.start).total_seconds()<1800 else []} for e in model.events]
    events += [{'id':f'sleep-band-{i}','start':b.start.isoformat(),'end':b.end.isoformat(),'display':'background','classNames':['sleep-band']} for i,b in enumerate(model.bands)]
    return events

def render_calendar(data,model,report,revision,mode='light',lang='vi'):
    p=PALETTES[mode];week=data.window.week_start
    events=calendar_events(data,model,report,mode)
    css=f''':root{{--fc-border-color:{p['border']};--fc-today-bg-color:transparent;--fc-page-bg-color:{p['surface']};--fc-neutral-bg-color:{p['surface']}}}
    body{{color:{p['text']};background:{p['surface']};font-family:Arial,sans-serif;margin:0}}
    .fc{{background:{p['surface']};color:{p['text']};padding:0 6px}}
    .fc .fc-scrollgrid{{border:0!important}}.fc th{{border:0!important;font-weight:600}}
    .fc .fc-col-header-cell-cushion{{padding:20px 2px;color:{p['muted']};font-size:14px;text-decoration:none;white-space:normal}}
    .fc .fc-day-today .fc-col-header-cell-cushion{{background:#c5dfff;color:#214d85;border-radius:24px;padding:12px 8px;margin:8px 0}}
    .fc .fc-timegrid-slot{{height:28px}}.fc .fc-timegrid-slot-label-cushion{{font-size:12px;color:{p['muted']};padding-right:12px}}
    .fc .fc-timegrid-slot-minor{{border-top:0}}
    .fc .fc-timegrid-event{{border-radius:7px;box-shadow:none;padding:3px 5px;border-width:2px}}
    .fc .fc-event-title{{font-size:12px;font-weight:600;line-height:1.3}}
    .fc .fc-event-time{{font-size:11px;font-weight:400}}
    .fc .fc-timegrid-now-indicator-container{{z-index:10;pointer-events:none}}
    .fc .fc-timegrid-now-indicator-line{{border-color:#ea4335;border-top-width:2px;z-index:10}}
    .fc .fc-timegrid-now-indicator-arrow{{border-color:#ea4335;z-index:10}}
    .fc .fc-bg-event.sleep-band{{background:repeating-linear-gradient(135deg,{p['stripe']} 0px,{p['stripe']} 5px,{p['surface']} 5px,{p['surface']} 10px)!important;opacity:1!important;border:1px solid {p['border']};box-sizing:border-box}}
    .short-event .fc-event-time{{display:none}}.fc .fc-timegrid-event:focus{{outline:3px solid #edb335}}
    '''
    return calendar(events=events,options={'initialView':'timeGridWeek','initialDate':week.isoformat(),'firstDay':1,'locale':'en-gb' if lang=='en' else 'vi','headerToolbar':False,'allDaySlot':False,'slotMinTime':'00:00:00','slotMaxTime':'24:00:00','height':820,'nowIndicator':True,'editable':False,'displayEventEnd':True,'dayHeaderFormat':{'weekday':'short','day':'numeric'},'eventTimeFormat':{'hour':'2-digit','minute':'2-digit','hour12':False},'slotLabelFormat':{'hour':'2-digit','minute':'2-digit','hour12':False},'scrollTime':initial_scroll_time(data.window),'scrollTimeReset':False},custom_css=css,callbacks=['eventClick'],key=f'calendar_v5_{revision}_{mode}_{lang}')
