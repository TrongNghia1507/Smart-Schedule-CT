from copy import deepcopy
from ..domain.validation import ValidationReport
from .services import TaskInputService
from ..infrastructure.repositories import InMemoryRepository
from ..infrastructure.io import CsvXlsxGateway

class ImportExportService:
    def preview(self,service,content,fixed):
        rows,notes=CsvXlsxGateway().read_rows(content,fixed)
        temp=TaskInputService(deepcopy(service.data),InMemoryRepository(),service.now_override)
        results=[]
        for line,row in rows:
            report=temp.submit(row,fixed);results.append((line,report))
        return temp.data,results,notes
