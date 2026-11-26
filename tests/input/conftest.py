from pathlib import Path

import pytest

@pytest.fixture(scope="session")
def app_file():
    return str(Path(__file__).resolve().parents[2] / "apps" / "streamlit" / "app.py")


@pytest.fixture(autouse=True)
def isolate_ui_data(tmp_path,monkeypatch):
    monkeypatch.setenv('SCHEDULE_INPUT_DATA_DIR',str(tmp_path/'app-data'))


@pytest.fixture(autouse=True)
def signed_in_user(tmp_path, monkeypatch):
    """Các test giao diện chạy app.py như một người dùng đã đăng nhập."""
    from streamlit.testing.v1 import AppTest
    from user_portal.auth import User

    monkeypatch.setenv('SCHEDULE_PORTAL_DB', str(tmp_path / 'portal.db'))
    original = AppTest.from_file.__func__
    user = User(1, 'tester', 'Người thử', 'user')

    def from_file(cls, *args, **kwargs):
        app = original(cls, *args, **kwargs)
        app.session_state['auth_user'] = user
        return app

    monkeypatch.setattr(AppTest, 'from_file', classmethod(from_file))
