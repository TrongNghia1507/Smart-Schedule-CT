from pathlib import Path

import pytest

@pytest.fixture(scope="session")
def app_file():
    return str(Path(__file__).resolve().parents[2] / "apps" / "streamlit" / "app.py")


@pytest.fixture(autouse=True)
def isolate_ui_data(tmp_path,monkeypatch):
    monkeypatch.setenv('SCHEDULE_INPUT_DATA_DIR',str(tmp_path/'app-data'))
