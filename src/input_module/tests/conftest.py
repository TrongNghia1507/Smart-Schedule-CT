import pytest

@pytest.fixture(autouse=True)
def isolate_ui_data(tmp_path,monkeypatch):
    monkeypatch.setenv('SCHEDULE_INPUT_DATA_DIR',str(tmp_path/'app-data'))
