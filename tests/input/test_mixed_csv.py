from datetime import date,datetime
import pytest
from schedule_input.domain.models import ScheduleInput,PlanningWindow
from schedule_input.application.import_export import ImportExportService
from schedule_input.application.services import TaskInputService
from schedule_input.infrastructure.io import CsvXlsxGateway
from schedule_input.infrastructure.repositories import InMemoryRepository


def service():
    now=datetime(2030,1,7,6)
    return TaskInputService(ScheduleInput(PlanningWindow(date(2030,1,7),now)),InMemoryRepository(),now)


def test_example_import_and_combined_export_roundtrip():
    s=service()
    data,reports,notes=ImportExportService().preview_mixed(s,CsvXlsxGateway().example(s.data.window))
    assert not notes and all(not r.has_errors() for _,r in reports)
    assert len(data.fixed_tasks)==len(data.deadline_tasks)==1
    assert data.fixed_tasks[0].prep_min==15 and data.fixed_tasks[0].after_min==10
    assert not s.data._tasks  # preview does not mutate or persist original data
    exported=CsvXlsxGateway().write_mixed_rows(data)
    restored,reports,_=ImportExportService().preview_mixed(service(),exported)
    assert all(not r.has_errors() for _,r in reports)
    from schedule_input.application.mapper import TaskFactory
    def without_ids(data):
        return [{k:v for k,v in TaskFactory.to_dict(t).items() if k!='id'} for t in data._tasks.values()]
    assert without_ids(restored)==without_ids(data)


def test_mixed_invalid_rows_do_not_discard_valid_rows():
    content=('task_type,name,repeat,start,end,kind,deadline,remaining_min\n'
             'fixed,Class,T2,08:00,09:00,,,\n'
             'unknown,Wrong,,,,,,\n'
             'deadline,Missing deadline,,,,hard,,60\n'
             'deadline,Good,,,,soft,13/01/2030 23:59,60\n').encode()
    data,reports,_=ImportExportService().preview_mixed(service(),content)
    assert [(line,r.has_errors()) for line,r in reports]==[(2,False),(3,True),(4,True),(5,False)]
    assert len(data.fixed_tasks)==len(data.deadline_tasks)==1


@pytest.mark.parametrize('content',[
    'name,start,end\nA,08:00,09:00',
    'task_type;name;start;end\nfixed;A;08:00;09:00',
    'task_type,name,NAME\nfixed,A,A',
    'task_type,name\nfixed,A,extra',
])
def test_bad_headers_and_extra_cells(content):
    with pytest.raises(ValueError):CsvXlsxGateway().read_mixed_rows(content.encode())
