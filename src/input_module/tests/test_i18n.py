from pathlib import Path
from streamlit.testing.v1 import AppTest
from schedule_input.ui.i18n import tr
from schedule_input.ui.task_table import table_payload
from schedule_input.application.mapper import TaskFactory
from schedule_input.application.parsers import BoolParser
from schedule_input.domain.validation import ValidationService
from schedule_input.infrastructure.io import SampleDataProvider


def test_language_switch_preserves_tasks_and_navigation():
    app=AppTest.from_file(str(Path(__file__).parents[1]/'app.py'),default_timeout=30).run()
    next(b for b in app.button if b.label=='Dữ liệu mẫu').click().run()
    next(b for b in app.button if b.label=='Xác nhận nạp mẫu').click().run()
    before=[TaskFactory.to_dict(t) for t in app.session_state.service.data._tasks.values()]
    app.button_group(key='language_picker').set_value('en').run()
    assert not app.exception
    assert app.session_state.ui_language=='en' and app.query_params['lang']=='en'
    assert any(x.value=='General settings' for x in app.subheader)
    assert [TaskFactory.to_dict(t) for t in app.session_state.service.data._tasks.values()]==before
    app.button(key='theme_toggle').click().run()
    next(b for b in app.button if b.label=='Preview schedule').click().run()
    assert not app.exception and app.session_state.ui_theme=='dark'
    assert any('16 blocks' in x.value for x in app.caption)
    app.button_group(key='language_picker').set_value('vi').run()
    assert any(x.value=='Tóm tắt' for x in app.subheader)
    assert app.session_state.ui_theme=='dark'
    assert [TaskFactory.to_dict(t) for t in app.session_state.service.data._tasks.values()]==before


def test_english_form_and_errors():
    app=AppTest.from_file(str(Path(__file__).parents[1]/'app.py'),default_timeout=30)
    app.query_params['lang']='en'
    app.run()
    assert not app.exception
    assert any(e.value=='Please enter at least one task.' for e in app.error)
    app.button(key='add_False').click().run()
    assert app.select_slider[0].label=='Importance' and app.select_slider[0].options==['1','2','3']
    next(b for b in app.button if b.label=='Save').click().run()
    assert not app.exception
    assert any('A name is required' in e.value for e in app.error)
    assert len(app.session_state.service.data.deadline_tasks)==0


def test_english_table_roundtrip_and_user_text():
    data=SampleDataProvider().load()
    report=ValidationService().validate_all(data)
    rows=table_payload(data.fixed_tasks,True,report,'en')
    assert rows[1]['raw']['repeat']=='Mon–Sun'
    assert rows[0]['meta']['duration']=='3 h 30 min'
    assert rows[0]['meta']['rigidity']=='Rigid 100%'
    for original,row in zip(data.fixed_tasks,rows):
        restored,issues=TaskFactory.from_raw(row['raw'],True)
        assert not issues.has_errors()
        assert restored==original
    assert BoolParser.parse('Yes') is True and BoolParser.parse('No') is False
    name='Hạn chót ngoài tuần đang lập lịch.'
    message=f'Chồng giờ với “{name}”. Hãy sửa giờ hoặc độ co dãn.'
    assert tr(message,'en')==f'Overlaps with “{name}”. Adjust the time or flexibility.'
    assert tr(message,'vi')==message


def test_calendar_locale_preserves_events(monkeypatch):
    from schedule_input.ui import calendar_view
    from schedule_input.application.preview import PreviewService
    data=SampleDataProvider().load()
    model=PreviewService().build(data)
    report=ValidationService().validate_all(data)
    monkeypatch.setattr(calendar_view,'calendar',lambda **kwargs:kwargs)
    vi=calendar_view.render_calendar(data,model,report,0,'dark','vi')
    en=calendar_view.render_calendar(data,model,report,0,'dark','en')
    assert vi['options']['locale']=='vi' and en['options']['locale']=='en-gb'
    assert vi['events']==en['events']
    assert vi['key']!=en['key']


def test_current_time_scroll():
    from datetime import datetime,date
    from schedule_input.domain.models import PlanningWindow
    from schedule_input.ui.calendar_view import initial_scroll_time
    assert initial_scroll_time(PlanningWindow(date(2026,11,2),datetime(2026,11,7,14,6)))=='13:06:00'
    assert initial_scroll_time(PlanningWindow(date(2026,11,2),datetime(2026,11,2,0,30)))=='00:00:00'
    assert initial_scroll_time(PlanningWindow(date(2026,10,19),datetime(2026,11,7,14,6)))=='06:00:00'


def test_switch_to_current_week():
    from datetime import datetime,timedelta
    app=AppTest.from_file(str(Path(__file__).parents[1]/'app.py'),default_timeout=30).run()
    next(b for b in app.button if b.label=='Dữ liệu mẫu').click().run()
    next(b for b in app.button if b.label=='Xác nhận nạp mẫu').click().run()
    next(b for b in app.button if b.label=='Xem trước lịch').click().run()
    assert any('Vạch đỏ' in i.value for i in app.info)
    before=app.session_state.service.data.fixed_tasks
    planned=app.session_state.service.data.window.week_start
    saved=app.session_state.service.repository.path.read_bytes()
    app.button(key='current_week').click().run()
    assert not app.exception
    today=datetime.now().date()
    assert app.session_state.service.data.window.week_start==planned
    assert app.session_state.preview_current_week is True
    assert app.session_state.service.data.fixed_tasks==before
    assert not any('Vạch đỏ' in i.value for i in app.info)
    assert app.session_state.service.repository.path.read_bytes()==saved
    app.button_group(key='language_picker').set_value('en').run()
    assert app.button(key='planning_week').label=='← Back to planning week'
    app.button(key='planning_week').click().run()
    assert not app.exception and app.session_state.preview_current_week is False
    assert app.session_state.service.data.window.week_start==planned
    assert app.session_state.service.repository.path.read_bytes()==saved
    assert any('The red line' in i.value for i in app.info)
