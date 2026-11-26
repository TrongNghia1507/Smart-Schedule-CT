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
