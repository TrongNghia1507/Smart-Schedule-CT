from datetime import date, datetime
import pytest
from schedule_input.application.mapper import TaskFactory
from schedule_input.application.calendar_edit import moved_task
from schedule_input.domain.models import *
from schedule_input.domain.validation import ValidationService,free_minutes
from schedule_input.infrastructure.repositories import JsonFileRepository

def task(**kwargs):
    raw=dict(name='Class',repeat='mon',start='08:00',end='09:00',prep_min=30)
    raw.update(kwargs)
    value,report=TaskFactory.from_raw(raw,True)
    assert not report.has_errors()
    return value

def test_preparation_roundtrip_and_overlap(tmp_path):
    data=ScheduleInput(PlanningWindow(date(2026,11,16),datetime(2026,11,16)))
    first=task(); data.add(first)
    other=task(name='Earlier',start='07:00',end='07:40',prep_min=0);data.add(other)
    assert any(i.code=='F04' for i in ValidationService().validate_all(data).issues)
    repo=JsonFileRepository(tmp_path/'draft.json');repo.save(data,None)
    loaded,_,notes=repo.load(data)
    assert not notes and loaded.get_by_id(first.id).prep_min==30
    assert TaskFactory.to_dict(first)['prep_min']==30

@pytest.mark.parametrize('prep',[-1,91])
def test_invalid_preparation(prep):
    _,report=TaskFactory.from_raw(dict(name='Class',repeat='mon',start='08:00',end='09:00',prep_min=prep),True)
    assert report.has_errors()

@pytest.mark.parametrize('minutes',[0,60])
def test_after_time_roundtrip_and_reserved_capacity(tmp_path,minutes):
    original=task(prep_min=0,after_min=minutes)
    data=ScheduleInput(PlanningWindow(date(2026,11,16),datetime(2026,11,16)))
    data.add(original)
    available=free_minutes(data)
    repo=JsonFileRepository(tmp_path/'draft.json');repo.save(data,None)
    loaded,_,notes=repo.load(data)
    assert not notes and loaded.get_by_id(original.id).after_min==minutes
    from dataclasses import replace
    data.update(replace(original,after_min=0))
    assert free_minutes(data)-available==minutes
    data.update(original)
    data.add(task(name='Next',start='09:30',end='10:30',prep_min=0))
    assert any(i.code=='F04' for i in ValidationService().validate_all(data).issues)==bool(minutes)

@pytest.mark.parametrize('minutes',[-1,61])
def test_invalid_after_time(minutes):
    _,report=TaskFactory.from_raw(dict(name='Class',repeat='mon',start='08:00',end='09:00',after_min=minutes),True)
    assert report.has_errors()

def test_move_series_preserves_duration_and_preparation():
    original=task(repeat='mon,wed')
    moved=moved_task(original,'2026-11-16T08:00:00','2026-11-17T08:20:00')
    assert moved.time_range.start==500 and moved.duration_min==60 and moved.prep_min==30
    assert moved.repeat.days==frozenset([Weekday.TUE,Weekday.THU])
    assert original.time_range.start==480

def test_move_one_off_across_midnight():
    original=task(repeat='',one_off_date='2026-11-16',start='23:30',end='00:30')
    moved=moved_task(original,'2026-11-16T23:30:00','2026-11-17T00:10:00')
    assert moved.repeat.one_off_date==date(2026,11,17)
    assert moved.time_range==TimeRange(10,70)
    with pytest.raises(ValueError):moved_task(original,'2026-11-16T23:30:00','2026-11-16T23:35:00')

def test_free_deadline_form(app_file):
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_file(app_file,default_timeout=30).run()
    app.button(key='add_False').click().run()
    next(c for c in app.checkbox if c.label=='Không có hạn chót cụ thể').check().run()
    assert not app.exception
    assert not any(d.label=='Ngày hạn chót' for d in app.date_input)

def test_fixed_form_saves_and_reopens_after_time(app_file):
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_file(app_file,default_timeout=30).run()
    app.button(key='add_True').click().run()
    next(x for x in app.text_input if x.label=='Tên công việc').set_value('After time regression')
    next(x for x in app.text_input if x.label=='Giờ bắt đầu (HH:mm)').set_value('14:00')
    next(x for x in app.text_input if x.label=='Giờ kết thúc (cho phép 24:00)').set_value('15:00')
    next(x for x in app.slider if x.label=='Thời gian dự trù sau công việc (phút)').set_value(35).run()
    next(b for b in app.button if b.label=='Lưu').click().run()
    assert not app.exception
    service=app.session_state.service
    saved=next(t for t in service.data.fixed_tasks if t.name=='After time regression')
    assert saved.after_min==35
    loaded,_,_=service.repository.load(service.data)
    assert loaded.get_by_id(saved.id).after_min==35
    app.session_state.edit_request=(True,saved.id)
    app.run()
    assert next(x for x in app.slider if x.label=='Thời gian dự trù sau công việc (phút)').value==35

def test_old_table_update_preserves_reserves(tmp_path):
    from schedule_input.application.services import TaskInputService
    data=ScheduleInput(PlanningWindow(date(2026,11,16),datetime(2026,11,16)))
    original=task(after_min=35);data.add(original)
    service=TaskInputService(data,JsonFileRepository(tmp_path/'draft.json'))
    row=TaskFactory.to_row_view(original)
    row.pop('after_min');row.pop('prep_min');row['name']='Renamed'
    assert not service.submit(row,True).has_errors()
    assert service.data.get_by_id(original.id).after_min==35
    row['after_min']=0
    assert not service.submit(row,True).has_errors()
    assert service.data.get_by_id(original.id).after_min==0

def test_calendar_callback_saves_once_and_rolls_back_conflict(tmp_path):
    from schedule_input.application.services import TaskInputService
    from schedule_input.application.calendar_callback import handle_calendar_event
    data=ScheduleInput(PlanningWindow(date(2026,11,16),datetime(2026,11,16)))
    original=task(prep_min=0);data.add(original)
    data.add(task(name='Busy',start='10:00',end='11:00',prep_min=0))
    service=TaskInputService(data,JsonFileRepository(tmp_path/'draft.json'))
    state={'snapshot':'obsolete','rev':7}
    def event(old,new,generation):
        return {'callback':'eventChange','eventChange':{
            'oldEvent':{'start':old},'event':{'start':new,
            'extendedProps':{'task_id':original.id,'sync_revision':generation}}}}
    first=event('2026-11-16T08:00:00','2026-11-16T08:20:00',0)
    handle_calendar_event(service,state,first)
    assert service.data.get_by_id(original.id).time_range.start==500
    assert state['rev']==7 and 'snapshot' not in state and state['calendar_sync']==1
    handle_calendar_event(service,state,first)
    assert len(service.history)==1  # stale callback does not move the task twice
    handle_calendar_event(service,state,event('2026-11-16T08:20:00','2026-11-16T10:00:00',1))
    assert state['calendar_error'].has_errors() and state['calendar_sync']==2
    assert service.data.get_by_id(original.id).time_range.start==500
    loaded,_,_=service.repository.load(service.data)
    assert loaded.get_by_id(original.id).time_range.start==500

def test_color_is_separate_from_task_json(tmp_path, app_file):
    from streamlit.testing.v1 import AppTest
    from schedule_input.ui.preferences import COLORS,load_colors
    app=AppTest.from_file(app_file,default_timeout=30).run()
    fixed=task(); app.session_state.service.data.add(fixed)
    app.session_state.page='preview'; app.session_state.edit_request=(True,fixed.id)
    app.run()
    assert not app.exception
    next(b for b in app.button if b.help==COLORS[0]).click().run()
    assert not app.exception
    next(b for b in app.button if b.label=='Lưu').click().run()
    assert not app.exception
    assert app.session_state.task_colors[fixed.id]==COLORS[0]
    assert 'color' not in TaskFactory.to_dict(app.session_state.service.data.get_by_id(fixed.id))
    assert load_colors(app.session_state.service.repository.path.with_name('calendar_colors.json'))[fixed.id]==COLORS[0]
