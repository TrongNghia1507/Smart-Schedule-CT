import re
from datetime import datetime, date
from ..domain.models import Weekday

class DurationParser:
    @staticmethod
    def parse(value):
        s=re.sub(r'\([^)]*\)','',str(value)).strip().lower()
        m=re.fullmatch(r'(\d+)h(?:(\d+)(?:p|m)?)?',s)
        if m:return int(m[1])*60+int(m[2] or 0)
        if re.fullmatch(r'-?\d+(?:p|m)?',s):return int(s.rstrip('pm'))
        raise ValueError('Nhập số phút nguyên, ví dụ 60, 60p hoặc 1h30.')
class DateTimeParser:
    @staticmethod
    def parse(value):
        s=str(value).strip()
        for fmt in ('%d/%m/%Y %H:%M','%Y-%m-%dT%H:%M','%Y-%m-%dT%H:%M:%S','%Y-%m-%d %H:%M:%S'):
            try:return datetime.strptime(s,fmt)
            except ValueError:pass
        raise ValueError('Nhập ngày giờ dd/mm/yyyy HH:mm hoặc ISO không múi giờ.')
    @staticmethod
    def day(value):
        for fmt in ('%d/%m/%Y','%Y-%m-%d'):
            try:return datetime.strptime(str(value).strip(),fmt).date()
            except ValueError:pass
        raise ValueError('Nhập ngày dd/mm/yyyy.')
    @staticmethod
    def time(value,end=False):
        s=str(value).strip()
        if end and s=='24:00':return 1440
        if not re.fullmatch(r'\d{1,2}:\d{2}',s):raise ValueError('Nhập giờ HH:mm.')
        h,m=map(int,s.split(':'))
        if h>23 or m>59:raise ValueError('Giờ phải từ 00:00 đến 23:59; kết thúc có thể là 24:00.')
        return h*60+m
class BoolParser:
    @staticmethod
    def parse(value):
        s=str(value).strip().casefold()
        if s in ('có','yes','true','1'):return True
        if s in ('không','no','false','0',''):return False
        raise ValueError('Chọn Có hoặc Không.')
class RepeatParser:
    @staticmethod
    def parse(value):
        s=str(value).lower().replace(' ','').replace('–','->')
        names=['t2','t3','t4','t5','t6','t7','cn']; days=list(Weekday)
        def index(s):return names.index(s) if s in names else [d.value for d in days].index(s)
        if not s:return frozenset()
        try:
            if '->' in s:
                a,b=map(index,s.split('->'))
                if a>b:raise ValueError()
                return frozenset(days[a:b+1])
            return frozenset(days[index(x)] for x in s.split(','))
        except ValueError:raise ValueError('Dùng T2, T5 hoặc T2->CN; không dùng khoảng ngược.')
