"""Calendar moves preserve duration and validate before persisting."""
from datetime import datetime, timedelta
from dataclasses import replace
from ..domain.models import FixedTask, TimeRange, RepeatRule, Weekday


def moved_task(task, old_start, new_start):
    if not isinstance(task, FixedTask):
        raise ValueError('Chỉ di chuyển việc cố định trên lịch xem trước.')
    old = datetime.fromisoformat(old_start.replace('Z', '+00:00')).replace(tzinfo=None)
    new = datetime.fromisoformat(new_start.replace('Z', '+00:00')).replace(tzinfo=None)
    delta = int((new-old).total_seconds()/60)
    if delta % 10:
        raise ValueError('Di chuyển theo bước 10 phút.')
    day_shift, start = divmod(task.time_range.start + delta, 1440)
    end = start + task.duration_min
    end = end if end <= 1440 else end % 1440
    rule = task.repeat
    if rule.is_one_off():
        rule = RepeatRule(one_off_date=rule.one_off_date+timedelta(days=day_shift))
    else:
        weekdays = list(Weekday)
        rule = RepeatRule(frozenset(weekdays[(weekdays.index(d)+day_shift)%7] for d in rule.days))
    return replace(task, repeat=rule, time_range=TimeRange(start,end))
