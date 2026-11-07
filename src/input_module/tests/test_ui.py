from pathlib import Path
from streamlit.testing.v1 import AppTest

def test_initial_page():
    app=AppTest.from_file(str(Path(__file__).parents[1]/'app.py'),default_timeout=30).run()
    assert not app.exception

def test_sample_preview_and_snapshot(tmp_path):
    from schedule_input.infrastructure.repositories import JsonFileRepository
    app=AppTest.from_file(str(Path(__file__).parents[1]/'app.py'),default_timeout=30).run()
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

def test_simplified_ui():
    app=AppTest.from_file(str(Path(__file__).parents[1]/'app.py'),default_timeout=30).run()
    labels=[x.label for x in app.button]+[x.label for x in app.text_input]+[x.label for x in app.checkbox]
    assert not any('Nhân bản' in s or 'giả lập' in s or 'Bây giờ' in s for s in labels)
    app.button(key='add_True').click().run()
    assert not app.exception
    assert not any('giờ ngủ' in x.label.lower() for x in app.checkbox)
    next(b for b in app.button if b.label=='Hủy').click().run()
    app.button(key='add_False').click().run()
    assert not app.exception
    assert app.select_slider[0].options==['1','2','3']

def test_theme_survives_navigation():
    app=AppTest.from_file(str(Path(__file__).parents[1]/'app.py'),default_timeout=30).run()
    assert app.session_state.ui_theme=='light'
    app.button(key='theme_toggle').click().run()
    assert not app.exception and app.session_state.ui_theme=='dark'
    next(b for b in app.button if b.label=='Xem trước lịch').click().run()
    assert not app.exception and app.session_state.ui_theme=='dark'
    app.button(key='theme_toggle').click().run()
    assert not app.exception and app.session_state.ui_theme=='light'
