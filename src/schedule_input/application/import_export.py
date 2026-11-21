from copy import deepcopy
from ..domain.validation import ValidationReport
from ..domain.models import Severity
from .services import TaskInputService
from ..infrastructure.repositories import InMemoryRepository
from ..infrastructure.io import CsvXlsxGateway,FIELDS

class ImportExportService:
    def preview_mixed(self,service,content):
        rows,notes=CsvXlsxGateway().read_mixed_rows(content)
        temp=TaskInputService(deepcopy(service.data),InMemoryRepository(),service.now_override)
        results=[]
        for line,row in rows:
            task_type=row.pop('task_type')
            if task_type not in ('fixed','deadline'):
                report=ValidationReport()
                report.add('CSV01',Severity.ERROR,'task_type','','task_type phải là fixed hoặc deadline.')
            else:
                fixed=task_type=='fixed'
                report=temp.submit({k:v for k,v in row.items() if k in FIELDS[fixed]},fixed)
            results.append((line,report))
        return temp.data,results,notes

    def preview(self,service,content,fixed):
        rows,notes=CsvXlsxGateway().read_rows(content,fixed)
        temp=TaskInputService(deepcopy(service.data),InMemoryRepository(),service.now_override)
        results=[]
        for line,row in rows:
            report=temp.submit(row,fixed);results.append((line,report))
        return temp.data,results,notes
