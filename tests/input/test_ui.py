from streamlit.testing.v1 import AppTest

def test_initial_page(app_file):
    app=AppTest.from_file(app_file,default_timeout=30).run()
    assert not app.exception

def test_sample_preview_and_snapshot(tmp_path, monkeypatch, app_file):
    from schedule_input.infrastructure.repositories import JsonFileRepository
    from schedule_input.ui import calendar_view

    calendars = []
    pending_click = []

    def capture_calendar(**kwargs):
        calendars.append(kwargs)
        if pending_click:
            from streamlit import session_state

            session_state[kwargs['key']] = pending_click.pop()
            kwargs['on_change']()

    monkeypatch.setattr(calendar_view, 'calendar', capture_calendar)
    app=AppTest.from_file(app_file,default_timeout=30).run()
    app.session_state.service.repository=JsonFileRepository(tmp_path/'draft.json')
    next(b for b in app.button if b.label=='Dữ liệu mẫu').click().run()
    next(b for b in app.button if b.label=='Xác nhận nạp mẫu').click().run()
    assert not app.exception
    assert len(app.session_state.service.data.deadline_tasks)==6
    next(b for b in app.button if b.label=='Xác nhận → Xem trước lịch').click().run()
    assert not app.exception
    assert any('16 khối' in c.value for c in app.caption)
    next(b for b in app.button if b.label=='Đúng rồi, tiếp tục').click().run()
    assert not app.exception
    assert len(app.session_state.snapshot.to_dict()['fixed_tasks'])==3
    next(b for b in app.button if b.label=='Chạy thuật toán xếp lịch').click().run()
    assert not app.exception
    planned = calendars[-1]
    assert planned['options']['editable'] is False
    assert planned['callbacks']==['eventClick']
    assert any('deadline-band' in event['classNames'] for event in planned['events'])
    assert not app.dataframe
    app.button(key='zoom_calendar').click().run()
    assert not app.exception and app.button(key='zoom_calendar').label=='Thu nhỏ'
    assert calendars[-1]['options']['height']=='100vh'
    assert calendars[-1]['key']==planned['key'] and calendars[-1]['events']==planned['events']
    deadline=next(event for event in calendars[-1]['events'] if 'deadline-band' in event['classNames'])
    pending_click.append({'callback':'eventClick','eventClick':{'event':deadline}})
    app.run()
    assert not app.exception
    assert any('**Mức quan trọng**' in item.value and '**Giờ đã xếp**' in item.value for item in app.markdown)
    assert not any(button.label=='Lưu' for button in app.button)
    app.button(key='zoom_calendar').click().run()
    assert not app.exception and app.button(key='zoom_calendar').label=='Phóng to'
    assert calendars[-1]['options']['height']==820

def test_simplified_ui(app_file):
    app=AppTest.from_file(app_file,default_timeout=30).run()
    labels=[x.label for x in app.button]+[x.label for x in app.text_input]+[x.label for x in app.checkbox]
    assert not any('Nhân bản' in s or 'giả lập' in s or 'Bây giờ' in s for s in labels)
    assert all(key in {box.key for box in app.expander} for key in ('table_card_True','table_card_False'))
    app.button(key='add_True').click().run()
    assert not app.exception
    assert not any('giờ ngủ' in x.label.lower() for x in app.checkbox)
    assert [toggle.label for toggle in app.toggle]==['Có thể xóa khi bận']
    assert not app.number_input
    next(b for b in app.button if b.label=='Hủy').click().run()
    app.button(key='add_False').click().run()
    assert not app.exception
    assert not app.selectbox
    mandatory=app.toggle[0]
    assert mandatory.label=='Bắt buộc' and mandatory.value
    assert app.select_slider[0].options==['1','2','3']
    app.text_input(key='form_None_1name').set_value('Việc tùy chọn')
    app.text_input(key='form_None_1remaining').set_value('60')
    app.checkbox(key='form_None_1free_deadline').check()
    mandatory.set_value(False)
    next(b for b in app.button if b.label=='Lưu').click().run()
    assert not app.exception
    assert app.session_state.service.data.deadline_tasks[0].mandatory is False

def test_theme_survives_navigation(app_file):
    app=AppTest.from_file(app_file,default_timeout=30).run()
    assert app.session_state.ui_theme=='light'
    app.button(key='theme_toggle').click().run()
    assert not app.exception and app.session_state.ui_theme=='dark'
    next(b for b in app.button if b.label=='Xem trước lịch').click().run()
    assert not app.exception and app.session_state.ui_theme=='dark'
    app.button(key='theme_toggle').click().run()
    assert not app.exception and app.session_state.ui_theme=='light'
