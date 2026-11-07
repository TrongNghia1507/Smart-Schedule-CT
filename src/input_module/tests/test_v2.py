import json
from datetime import datetime
from schedule_input.infrastructure.io import SampleDataProvider,CsvXlsxGateway
from schedule_input.infrastructure.repositories import JsonFileRepository
from schedule_input.application.mapper import TaskFactory
from schedule_input.application.services import TaskInputService
from schedule_input.domain.validation import ValidationService

def test_importance_limits():
    task=SampleDataProvider().load().deadline_tasks[0]
    row=TaskFactory.to_row_view(task)
    for n in (0,4,10):
        _,report=TaskFactory.from_raw(dict(row,importance=n))
        assert report.has_errors()
    for n in (1,2,3):
        _,report=TaskFactory.from_raw(dict(row,importance=n))
        assert not report.has_errors()

def test_demo_real_time():
    data=SampleDataProvider().demo()
    assert data.window.now<=datetime.now()
    assert all(t.deadline>datetime.now() for t in data.deadline_tasks)
    assert not ValidationService().validate_all(data).has_errors()
    assert b'is_sleep' not in CsvXlsxGateway().write_rows(data,True)

def test_repeated_calendar_events_keep_unique_ids():
    from schedule_input.application.preview import PreviewService
    from schedule_input.ui.calendar_view import calendar_events
    data=SampleDataProvider().load()
    events=calendar_events(data,PreviewService().build(data),ValidationService().validate_all(data))
    assert len(events)==30
    assert len({e['id'] for e in events})==30
    task=data.fixed_tasks[1]
    assert sum(e.get('extendedProps',{}).get('task_id')==task.id for e in events)==7

def test_migration_and_no_override(tmp_path):
    from pathlib import Path
    source=Path(__file__).parents[1]/'schedule_input/infrastructure/sample.json'
    path=tmp_path/'draft.json';path.write_bytes(source.read_bytes())
    repo=JsonFileRepository(path);data,override,notes=repo.load(SampleDataProvider().demo())
    assert [t.importance for t in data.deadline_tasks]==[1,1,2,3,3,1]
    assert override is None
    assert path.with_name('draft.v1.bak.json').exists()
    repo.save(data,datetime(2000,1,1))
    saved=json.loads(path.read_text(encoding='utf-8'))
    assert saved['schema_version']==2 and 'now_override' not in saved['settings']
    assert all('is_sleep' not in t for t in saved['fixed_tasks'])
    loaded,_,_=repo.load(data)
    assert [t.importance for t in loaded.deadline_tasks]==[1,1,2,3,3,1]
