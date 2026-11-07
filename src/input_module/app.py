from pathlib import Path
import os
from datetime import datetime,date,time,timedelta
from dataclasses import replace
from copy import deepcopy
from functools import partial
import streamlit as st
from schedule_input.ui.i18n import tr,language,weekday_labels
from streamlit_calendar import calendar
from schedule_input.domain.models import *
from schedule_input.domain.validation import *
from schedule_input.application.mapper import TaskFactory,hh,DefaultsProvider
from schedule_input.application.parsers import DateTimeParser
from schedule_input.application.services import TaskInputService
from schedule_input.application.preview import PreviewService
from schedule_input.application.import_export import ImportExportService
from schedule_input.infrastructure.repositories import JsonFileRepository
from schedule_input.infrastructure.io import SampleDataProvider,CsvXlsxGateway,FIELDS

st.set_page_config(page_title=tr('Quản lý lịch tuần',st.query_params.get('lang','vi')),page_icon='📅',layout='wide')
if st.session_state.get('app_version') != 4 or ('service' in st.session_state and type(st.session_state.service.data) is not ScheduleInput):
    st.session_state.clear()
    st.session_state.app_version=4
if 'service' not in st.session_state:
    now=datetime.now(); default=ScheduleInput(PlanningWindow(now.date()-timedelta(days=now.weekday()),now))
    repo=JsonFileRepository(Path(os.environ.get('SCHEDULE_INPUT_DATA_DIR',str(Path(__file__).parent/'data')))/'schedule_input_draft.json')
    data,override,notes=repo.load(default)
    st.session_state.service=TaskInputService(data,repo,override)
    st.session_state.notes=notes;st.session_state.page='input';st.session_state.rev=0
    st.session_state.old_week=data.window.week_start<default.window.week_start
from schedule_input.ui.theme import apply_theme,banner,status_badges
from schedule_input.ui.task_table import render_table
st.session_state.setdefault('ui_theme',st.query_params.get('theme','light') if st.query_params.get('theme','light') in ('light','dark') else 'light')
st.session_state.setdefault('ui_language',st.query_params.get('lang','vi') if st.query_params.get('lang','vi') in ('vi','en') else 'vi')
mode=st.session_state.ui_theme
apply_theme(mode)
s=st.session_state.service
s.now_override=None
s.data.window=replace(s.data.window,now=datetime.now())

def refresh():
    st.session_state.pop('snapshot',None)
    st.session_state.pop('edit_request',None)
    st.session_state.pop('table_error_True',None)
    st.session_state.pop('table_error_False',None)
    st.session_state.rev+=1;st.rerun()
def report_ui(report):
    for i in report.issues:
        label={'Error':st.error,'Warning':st.warning,'Info':st.info}[i.severity.value]
        task=s.data._tasks.get(i.task_id)
        label((task.name+' · ' if task else '')+tr(i.message))
def save_settings(window,override):
    candidate=deepcopy(s.data);candidate.window=window
    s.repository.save(candidate,override);s.history.append(s.data);s.data=candidate;s.now_override=override
def field_error(report,name):
    for issue in report.by_field(name):
        if issue.severity==Severity.ERROR:st.error(tr(issue.message))

@st.dialog(tr('Sửa công việc'),width='large')
def editor(fixed,id=None):
    raw=s.get_for_edit(id) if id else {}
    key=f'form_{id}_{st.session_state.rev}'
    row={}
    if raw.get('id'):row['id']=raw['id']
    row['name']=st.text_input(tr('Tên công việc'),raw.get('name',''),max_chars=100,key=key+'name')
    if fixed:
        labels=dict(zip([d.value for d in Weekday],weekday_labels()))
        days=st.pills(tr('Lặp hằng tuần'),list(labels),selection_mode='multi',default=raw.get('repeat','').split(',') if raw.get('repeat') else [],format_func=lambda x:labels[x],key=key+'days')
        row['repeat']=','.join(days)
        if not days:row['one_off_date']=st.date_input(tr('Ngày diễn ra'),value=DateTimeParser.day(raw['one_off_date']) if raw.get('one_off_date') else s.data.window.week_start,format='DD/MM/YYYY',key=key+'day').isoformat()
        a,b=st.columns(2)
        row['start']=a.text_input(tr('Giờ bắt đầu (HH:mm)'),raw.get('start',''),key=key+'start')
        row['end']=b.text_input(tr('Giờ kết thúc (cho phép 24:00)'),raw.get('end',''),key=key+'end')
        row['is_flexible']=st.toggle(tr('Có thể chia nhỏ và co dãn'),value=raw.get('is_flexible')=='Có',key=key+'flex')
        duration=1440
        try:
            duration=TimeRange(DateTimeParser.time(row['start']),DateTimeParser.time(row['end'],True)).duration_min();st.caption(tr(f'Thời lượng: {duration} phút'))
        except ValueError:pass
        row['min_duration_min']=st.number_input(tr('Thời lượng tối thiểu (phút)'),1,duration,min(int(raw.get('min_duration_min') or duration),duration),disabled=not row['is_flexible'],key=key+'minimum')
    else:
        row['kind']=st.selectbox(tr('Loại'), ['asap','hard','soft'],index=['asap','hard','soft'].index(raw['kind']) if raw.get('kind') else None,help=tr('asap: việc gấp · hard: hạn cứng · soft: hạn mềm'),key=key+'kind')
        row['importance']=st.select_slider(tr('Mức quan trọng'),options=[1,2,3],value=int(raw.get('importance') or 2),key=key+'importance')
        deadline=DateTimeParser.parse(raw['deadline']) if raw.get('deadline') else None
        a,b=st.columns(2)
        day=a.date_input(tr('Ngày hạn chót'),deadline.date() if deadline else None,format='DD/MM/YYYY',key=key+'deadline_day')
        clock=b.time_input(tr('Giờ hạn chót'),deadline.time() if deadline else time(23,59),step=60,key=key+'deadline_time')
        row['deadline']=datetime.combine(day,clock).isoformat(timespec='minutes') if day else ''
        row['remaining_min']=st.text_input(tr('Thời lượng (phút, ví dụ 60 hoặc 1h30)'),raw.get('remaining_min',''),key=key+'remaining')
        row['focus']=st.radio(tr('Mức tập trung'),['high','low'],index=0 if raw.get('focus','high')=='high' else 1,horizontal=True,key=key+'focus')
        row['buffer_min']=st.slider(tr('Nghỉ đệm sau cả việc'),0,60,int(raw.get('buffer_min') or 15),step=5,key=key+'buffer')
        with st.expander(tr('Tùy chọn nâng cao'),expanded=bool(raw)):
            row['earliest_start']=st.text_input(tr('Bắt đầu sớm nhất (dd/mm/yyyy HH:mm, có thể để trống)'),raw.get('earliest_start',''),key=key+'earliest')
            mn,mx=DefaultsProvider.chunk(row['focus']);a,b=st.columns(2)
            row['chunk_min']=a.number_input(tr('Chunk min'),1,value=int(raw.get('chunk_min') or mn),key=key+'mn'+row['focus'])
            row['chunk_max']=b.number_input(tr('Chunk max'),1,value=int(raw.get('chunk_max') or mx),key=key+'mx'+row['focus'])
    buttons=st.columns([1,1,2,1])
    if buttons[0].button(tr('Lưu'),type='primary',key=key+'save'):
        report=s.submit(row,fixed)
        if report.has_errors():report_ui(report)
        else:refresh()
    if id and buttons[3].button(tr('Xóa việc này'),key=key+'delete'):s.remove(id);refresh()
    if buttons[1].button(tr('Hủy'),key=key+'cancel'):refresh()

banner(st.session_state.page)
nav_input,nav_preview,_,language_col,theme_col=st.columns([1.2,1.5,2,1.3,1])
if nav_input.button(tr('Nhập dữ liệu'),type='primary' if st.session_state.page=='input' else 'secondary'):
    st.session_state.page='input';refresh()
if nav_preview.button(tr('Xem trước lịch'),type='primary' if st.session_state.page=='preview' else 'secondary'):
    st.session_state.page='preview';refresh()

if theme_col.button(tr('☾ Tối' if mode=='light' else '☀ Sáng'),key='theme_toggle',use_container_width=True):
    st.session_state.ui_theme='dark' if mode=='light' else 'light'
    st.query_params['theme']=st.session_state.ui_theme
    st.rerun()

def change_language():
    st.session_state.ui_language=st.session_state.language_picker
    st.query_params['lang']=st.session_state.ui_language

language_col.segmented_control(tr('Ngôn ngữ'),['vi','en'],default=language(),format_func=lambda value:'Vie' if value=='vi' else 'Eng',selection_mode='single',required=True,key='language_picker',on_change=change_language,label_visibility='collapsed',width='stretch')

if st.session_state.notes:
    with st.expander(tr('Thông báo về dữ liệu đã mở')):
        for note in st.session_state.notes:st.info(tr(note))
if s.repository.blocked:
    st.error(tr('File nháp được bảo vệ. Chọn file mới để tiếp tục.'))
    if st.button(tr('Dùng file nháp mới')):
        s.repository=JsonFileRepository(Path(__file__).parent/'data'/f'draft_{datetime.now():%Y%m%d_%H%M%S}.json');st.session_state.notes=[];refresh()
    st.stop()
if st.session_state.old_week:
    st.warning(tr('File nháp đang dùng tuần cũ. Bạn muốn giữ tuần hay chuyển sang tuần hiện tại?'))
    a,b=st.columns(2)
    if a.button(tr('Giữ tuần cũ')):st.session_state.old_week=False;refresh()
    if b.button(tr('Chuyển sang tuần hiện tại')):
        now=datetime.now();save_settings(replace(s.data.window,week_start=now.date()-timedelta(days=now.weekday()),now=now),None);st.session_state.old_week=False;refresh()
    st.stop()

if st.session_state.page=='input':
    with st.container(border=True,key='settings_card'):
        st.subheader(tr('Thiết lập chung'))
        with st.form('settings'):
            w,a,b=st.columns([2,1,1])
            week=w.date_input(tr('Tuần lập lịch (chọn Thứ Hai)'),s.data.window.week_start,format='DD/MM/YYYY')
            ss=a.text_input(tr('Bắt đầu ngủ mặc định'),hh(s.data.window.sleep.start));se=b.text_input(tr('Kết thúc ngủ mặc định'),hh(s.data.window.sleep.end))
            st.caption(tr('Giờ ngủ được kẻ sọc trên lịch, không cần nhập thành công việc.'))
            if st.form_submit_button(tr('Áp dụng thiết lập')):
                try:
                    if week.weekday()!=0:raise ValueError('Hãy chọn ngày Thứ Hai.')
                    sleep_range=TimeRange(DateTimeParser.time(ss),DateTimeParser.time(se,True));save_settings(PlanningWindow(week,datetime.now(),SleepWindow(sleep_range.start,sleep_range.end)),None);refresh()
                except ValueError as ex:st.error(tr(str(ex)))
    a,b,c=st.columns(3)
    if a.button(tr('Dữ liệu mẫu')):
        st.session_state.ask_sample=True
    if b.button(tr('Hoàn tác'),disabled=not s.history):s.undo();refresh()
    if c.button(tr('Xóa toàn bộ')):st.session_state.ask_clear=True
    if st.session_state.get('ask_sample'):
        st.warning(tr('Nạp mẫu sẽ thay dữ liệu hiện tại; có thể hoàn tác. Các hạn chót mẫu được dời sang tuần tới để dùng với giờ hiện tại.'))
        if st.button(tr('Xác nhận nạp mẫu')):
            candidate=SampleDataProvider().demo();s.repository.save(candidate,None);s.history.append(s.data);s.data=candidate;s.now_override=None;st.session_state.ask_sample=False;refresh()
    if st.session_state.get('ask_clear'):
        if st.button(tr('Xác nhận xóa toàn bộ')):
            candidate=ScheduleInput(s.data.window);s.repository.save(candidate,s.now_override);s.history.append(s.data);s.data=candidate;st.session_state.ask_clear=False;refresh()
    table_errors=False;report=s.review()
    for fixed,title in ((True,'A. Việc cố định'),(False,'B. Việc có deadline')):
        with st.container(border=True,key=f'table_card_{fixed}'):
            tasks=s.data.fixed_tasks if fixed else s.data.deadline_tasks
            heading,add=st.columns([5,1]);heading.subheader(tr(f'{title} · {len(tasks)} việc'))
            if add.button(tr('+ Thêm bằng form'),key=f'add_{fixed}',type='primary'):st.session_state.edit_request=(fixed,None)
            event=render_table(tasks,fixed,report,mode,st.session_state.rev,language())
            if event and event.get('nonce')!=st.session_state.get(f'table_event_{fixed}'):
                st.session_state[f'table_event_{fixed}']=event['nonce']
                if event['action']=='edit':st.session_state.edit_request=(fixed,event['id'])
                elif event['action']=='remove':s.remove(event['id']);refresh()
                elif event['action']=='submit':
                    result=s.submit(event['raw'],fixed)
                    if result.has_errors():st.session_state[f'table_error_{fixed}']=result
                    else:st.session_state.pop(f'table_error_{fixed}',None);refresh()
            error=st.session_state.get(f'table_error_{fixed}')
            if error:
                table_errors=True;report_ui(error)
                st.caption(tr('Thay đổi chưa được lưu. Sửa lại ô hoặc hủy thay đổi.'))
                if st.button(tr('Hủy thay đổi chưa hợp lệ'),key=f'discard_{fixed}'):
                    st.session_state.pop(f'table_error_{fixed}',None);refresh()
            with st.expander(tr('Xuất dữ liệu bảng')):
                st.download_button(tr('Xuất CSV'),CsvXlsxGateway().write_rows(s.data,fixed),file_name=('fixed_tasks' if fixed else 'deadline_tasks')+'.csv',mime='text/csv',key=f'export_{fixed}')
    with st.expander(tr('Nhập CSV')):
        fixed=st.radio(tr('Loại bảng'),['Việc cố định','Việc có hạn chót'],format_func=partial(tr,lang=language()))=='Việc cố định'
        upload=st.file_uploader(tr('Chọn CSV UTF-8'),type=['csv'])
        if upload:
            try:
                candidate,results,unknown=ImportExportService().preview(s,upload.getvalue(),fixed)
                if unknown:st.info(tr('Bỏ qua cột: '+', '.join(unknown)))
                for line,report in results:
                    if report.issues:st.write(tr(f'Dòng {line}'));report_ui(report)
                valid=sum(not report.has_errors() for _,report in results)
                if st.button(tr(f'Nhập {valid} dòng hợp lệ'),disabled=valid==0):
                    s.repository.save(candidate,s.now_override);s.history.append(s.data);s.data=candidate;refresh()
            except (ValueError,UnicodeError) as ex:st.error(tr(str(ex)))
    report=s.review()
    with st.container(border=True,key="footer_card"):
        a,b=st.columns([3,2])
        with a:status_badges(report)
        if b.button(tr('Xác nhận → Xem trước lịch'),key='confirm_input',type='primary',disabled=report.has_errors() or table_errors):st.session_state.page='preview';refresh()
        if report.issues:
            with st.expander(tr('Chi tiết kiểm tra dữ liệu')):report_ui(report)
else:
    from schedule_input.ui.calendar_view import render_calendar
    preview_data=deepcopy(s.data)
    if st.session_state.get('preview_current_week',False):
        now=datetime.now()
        preview_data.window=replace(preview_data.window,week_start=now.date()-timedelta(days=now.weekday()),now=now)
    model=PreviewService().build(preview_data);report=s.review()
    main,side=st.columns([4,1.25],gap='large')
    with main:
        with st.container(border=True,key='calendar_card'):
            st.subheader(tr(f'{preview_data.window.week_start:%d/%m} – {preview_data.window.week_end():%d/%m/%Y}'))
            if st.session_state.get('preview_current_week',False):
                st.caption(tr('Đang xem tuần hiện tại. Tuần lập lịch và dữ liệu đã lưu được giữ nguyên.'))
                if st.button(tr('← Quay lại tuần đang lập lịch'),key='planning_week'):
                    st.session_state.preview_current_week=False
                    refresh()
            if not preview_data.window.contains(preview_data.window.now):
                st.info(tr('Vạch đỏ chỉ hiện trong tuần có ngày hôm nay. Tuần đang xem không chứa ngày hiện tại.'))
                if st.button(tr('Xem tuần hiện tại'),key='current_week'):
                    st.session_state.preview_current_week=True
                    refresh()
            result=render_calendar(preview_data,model,report,st.session_state.rev,mode,language())
            if result.get('callback')=='eventClick':
                clicked=result['eventClick']['event']
                id=clicked.get('extendedProps',{}).get('task_id')
                if id in s.data._tasks:st.session_state.edit_request=(True,id)
    with side:
        with st.container(border=True,key="summary_card"):
            st.subheader(tr('Tóm tắt'))
            st.markdown(tr(f'**{len(s.data.fixed_tasks)} việc cố định**'))
            st.caption(tr(f'{len(model.events)} khối · {len(model.bands)} dải ngủ mặc định'))
            status_badges(report)
        with st.container(border=True,key="legend_card"):
            st.subheader(tr('Chú giải'))
            st.html('<div class="legend"><span class="swatch"></span>'+tr('Việc cố định (tên + giờ)')+'</div><div class="legend"><span class="swatch sleep"></span>'+tr('Giờ ngủ')+' '+hh(s.data.window.sleep.start)+'–'+hh(s.data.window.sleep.end)+'</div><div class="legend"><span class="swatch line"></span>'+tr('Thời gian hiện tại')+'</div><div class="legend">'+tr('↔ Có thể chia nhỏ / co dãn')+'</div>')
            st.caption(tr('Bấm vào một việc để sửa nhanh. Việc có deadline chưa được xếp nên chưa hiện ở đây.'))
        if st.button(tr('← Quay lại nhập'),use_container_width=True):st.session_state.page='input';refresh()
        if st.button(tr('Đúng rồi, tiếp tục'),key='confirm_snapshot',type='primary',disabled=report.has_errors(),use_container_width=True):
            try:st.session_state.snapshot=s.confirm();st.success(tr('Đã tạo InputSnapshot, sẵn sàng cho Ranking.'))
            except ValueError as ex:st.error(tr(str(ex)))
        if st.session_state.get('snapshot'):st.download_button(tr('Xuất snapshot JSON để debug'),st.session_state.snapshot.to_json(),'input_snapshot.json',mime='application/json')
        if report.issues:
            with st.expander(tr('Chi tiết kiểm tra')):report_ui(report)

if st.session_state.get('edit_request'):editor(*st.session_state.edit_request)
