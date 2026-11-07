from copy import deepcopy
from .mapper import TaskFactory
from .preview import SnapshotBuilder
from ..domain.validation import ValidationService,ValidationReport
from ..domain.models import *

class TaskInputService:
    def __init__(self,data,repository,now_override=None):self.data=data;self.repository=repository;self.now_override=now_override;self.history=[]
    def sync_clock(self):
        if self.now_override is None:
            from dataclasses import replace
            self.data.window=replace(self.data.window,now=datetime.now())
    def review(self):
        self.sync_clock()
        return ValidationService().validate_all(self.data)
    def persist(self):self.repository.save(self.data,self.now_override)
    def submit(self,raw,fixed=False):
        self.sync_clock()
        task,report=TaskFactory.from_raw(raw,fixed)
        if not task:return report
        candidate=deepcopy(self.data)
        if task.id in candidate._tasks:candidate.update(task)
        else:candidate.add(task)
        all_report=ValidationService().validate_all(candidate)
        report.issues.extend(i for i in all_report.issues if i.task_id==task.id)
        if report.has_errors():return report
        self.repository.save(candidate,self.now_override)
        self.history.append(self.data);self.data=candidate
        return report
    def submit_deadline_task(self,raw):return self.submit(raw)
    def submit_fixed_task(self,raw):return self.submit(raw,True)
    def get_for_edit(self,id):return TaskFactory.to_row_view(self.data.get_by_id(id))
    def update(self,id,raw):return self.submit(dict(raw,id=id),isinstance(self.data.get_by_id(id),FixedTask))
    def remove(self,id):
        candidate=deepcopy(self.data);candidate.remove(id);self.repository.save(candidate,self.now_override);self.history.append(self.data);self.data=candidate
    def undo(self):
        if self.history:
            candidate=self.history[-1];self.repository.save(candidate,self.now_override);self.data=self.history.pop()
    def confirm(self):
        self.sync_clock()
        return SnapshotBuilder().build(self.data)
    def replace_rows(self,rows,fixed):
        self.sync_clock()
        candidate=deepcopy(self.data); report=ValidationReport()
        for t in candidate.fixed_tasks if fixed else candidate.deadline_tasks:candidate.remove(t.id)
        for raw in rows:
            if not any(str(v or '').strip() for v in raw.values()):continue
            task,result=TaskFactory.from_raw(raw,fixed);report.issues.extend(result.issues)
            if task:
                if task.id in candidate._tasks:report.add('V01',Severity.ERROR,'id',task.id,'ID trùng trong bảng.')
                else:candidate.add(task)
        report.issues.extend(i for i in ValidationService().validate_all(candidate).issues if i.code!='G02')
        if not report.has_errors():
            self.repository.save(candidate,self.now_override);self.history.append(self.data);self.data=candidate
        return report
