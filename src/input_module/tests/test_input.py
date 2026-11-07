import json
from datetime import datetime,date
from dataclasses import replace,FrozenInstanceError
import pytest
from schedule_input.infrastructure.io import SampleDataProvider,CsvXlsxGateway
from schedule_input.infrastructure.repositories import JsonFileRepository,InMemoryRepository
from schedule_input.application.services import TaskInputService
from schedule_input.application.mapper import TaskFactory
from schedule_input.application.parsers import *
from schedule_input.application.preview import PreviewService,SnapshotBuilder
from schedule_input.application.import_export import ImportExportService
from schedule_input.domain.models import *
from schedule_input.domain.validation import *

@pytest.fixture
def data():return SampleDataProvider().load()
def fixed(**kw):
    row=dict(name='Việc thử',repeat='T2',start='13:00',end='14:00',is_flexible='Không',is_sleep='Không');row.update(kw)
    t,r=TaskFactory.from_raw(row,True);assert not r.has_errors();return t
def test_golden(data):
    report=ValidationService().validate_all(data)
    assert not report.has_errors()
    assert sorted(i.code for i in report.issues)==['V06','V13','V13','V14','V14']
    preview=PreviewService().build(data)
    assert len(data.fixed_tasks)==3 and len(data.deadline_tasks)==6
    assert len(preview.events)==16 and len(preview.bands)==14
@pytest.mark.parametrize('value,result',[('60p',60),('1h30',90),(' 60 ',60),('210p (Cứng 100%)',210)])
def test_duration(value,result):assert DurationParser.parse(value)==result
def test_repeat():
    assert len(RepeatParser.parse('T2->CN'))==7
    assert len(RepeatParser.parse('t2,T2'))==1
    with pytest.raises(ValueError):RepeatParser.parse('T5->T2')
def test_full_day():
    assert TimeRange(0,1440).duration_min()==1440
    with pytest.raises(ValueError):TimeRange(300,300)
def test_midnight_boundary(data):
    t=fixed(repeat='CN',start='23:00',end='05:00');data.add(t)
    occurrences=t.occurrences(data.window.week_start)
    assert len(occurrences)==2
    events=[e for e in PreviewService().build(data).events if e.task_id==t.id]
    assert len(events)==2
    assert events[0].start==datetime(2026,10,19) and events[0].end.hour==5
    assert events[-1].end==datetime(2026,10,26)
def test_sleep_per_day(data):
    data.add(fixed(repeat='',one_off_date='21/10/2026',start='23:00',end='05:00',is_sleep='Có'))
    assert len(sleep_bands(data))==14
    assert all(not task.is_sleep for task in data.fixed_tasks)
def test_sleep_outside_week(data):
    data.add(fixed(repeat='',one_off_date='30/10/2026',is_sleep='Có'))
    assert len(sleep_bands(data))==14
def test_overlap_rigid_and_flexible(data):
    data.add(fixed(start='07:30',end='08:00',is_flexible='Có',min_duration_min=30))
    assert any(i.code=='F04' and i.severity==Severity.ERROR for i in ValidationService().validate_all(data).issues)
    t=data.fixed_tasks[-1];data.update(replace(t,flexibility=Flexibility(15,30)))
    assert not ValidationService().validate_all(data).has_errors()
def test_sleep_double_warning_and_error(data):
    data.add(fixed(name='Ngủ 1',is_sleep='Có'));data.add(fixed(name='Ngủ 2',is_sleep='Có'))
    issues=ValidationService().validate_all(data).issues
    assert any(i.code=='F04' and i.severity==Severity.ERROR for i in issues)
    assert not any(i.code=='F08' for i in issues)
def test_adjacent_not_overlap(data):
    data.add(fixed(start='11:00',end='11:30'))
    assert not ValidationService().validate_all(data).has_errors()
def test_atomic_reject(data):
    service=TaskInputService(data,InMemoryRepository(),data.window.now)
    original=service.data
    result=service.submit_fixed_task(dict(name='Trùng',repeat='T2',start='08:00',end='09:00'))
    assert result.has_errors() and service.data is original
def test_multiple_invalid_fields():
    t,r=TaskFactory.from_raw(dict(name='',kind='urgent',deadline='bad',importance=20,remaining_min=0,chunk_min=90,chunk_max=30))
    assert t is None and len(r.issues)>=6
def test_buffer_step():
    with pytest.raises(ValueError):BufferPolicy(7)
def test_snapshot(data):
    snap=SnapshotBuilder().build(data)
    result=snap.to_dict();result['fixed_tasks'].clear()
    assert len(snap.to_dict()['fixed_tasks'])==3
    with pytest.raises(FrozenInstanceError):snap.payload='bad'
    assert 'default_bands' in snap.to_dict()['window']['sleep']
def test_round_trip(data,tmp_path):
    repo=JsonFileRepository(tmp_path/'draft.json');repo.save(data,data.window.now)
    restored,override,notes=repo.load(ScheduleInput(data.window))
    assert restored.fixed_tasks==data.fixed_tasks and restored.deadline_tasks==data.deadline_tasks
    assert override is None and not notes
def test_old_deadline_retained(data,tmp_path):
    repo=JsonFileRepository(tmp_path/'draft.json');repo.save(data,None)
    restored,_,_=repo.load(ScheduleInput(data.window))
    restored.window=replace(restored.window,now=datetime(2026,11,6))
    assert len(restored.deadline_tasks)==6
    assert any(i.code=='V05' for i in ValidationService().validate_all(restored).issues)
def test_corrupt_and_future(data,tmp_path):
    path=tmp_path/'draft.json';repo=JsonFileRepository(path);path.write_text('{bad')
    restored,_,notes=repo.load(data);assert notes and list(tmp_path.glob('*.corrupt.*.json'))
    path.write_text('{"schema_version": 999}')
    repo.load(data)
    with pytest.raises(ValueError):repo.save(data,None)
    assert json.loads(path.read_text())['schema_version']==999
@pytest.mark.parametrize('fixed',[True,False])
def test_csv_roundtrip(data,fixed):
    gateway=CsvXlsxGateway();rows,notes=gateway.read_rows(gateway.write_rows(data,fixed),fixed)
    assert not notes
    for _,row in rows:
        t,r=TaskFactory.from_raw(row,fixed);assert t and not r.has_errors()
def test_partial_import(data):
    service=TaskInputService(data,InMemoryRepository(),data.window.now)
    candidate,results,_=ImportExportService().preview(service,'name,repeat,start,end\nHợp lệ,T2,14:00,15:00\nSai,T2,08:00,09:00'.encode(),True)
    assert len(candidate.fixed_tasks)==4
    assert not results[0][1].has_errors() and results[1][1].has_errors()
def test_union_free_time(data):
    empty=ScheduleInput(data.window)
    before=free_minutes(empty)
    empty.add(fixed(start='13:00',end='14:00'));empty.add(fixed(start='13:30',end='14:30'))
    assert before-free_minutes(empty)==90
