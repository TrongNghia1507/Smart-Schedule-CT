import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.web.app import app
from backend.web.migrate import migrate
from backend.web.storage import db_path
from user_portal import auth, rating_schema
from user_portal.db import connect

API = "/api/v1"
PASSWORD = "test-password"


@pytest.fixture(autouse=True)
def portal(tmp_path, monkeypatch):
    monkeypatch.delenv("SCHEDULE_PORTAL_DB", raising=False)
    monkeypatch.setenv("SCHEDULE_WEB_DATA_DIR", str(tmp_path / "web"))
    monkeypatch.setenv("SCHEDULE_ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setenv("SCHEDULE_SECURE_COOKIE", "false")
    monkeypatch.setenv("AI_ENABLED", "false")


def register(client, username):
    response = client.post(API + "/auth/register", json={
        "username": username, "full_name": "Người kiểm thử", "email": "",
        "user_group": auth.USER_GROUPS[0], "password": PASSWORD, "confirm": PASSWORD, "consent": True,
    })
    assert response.status_code == 201, response.text
    return {"X-CSRF-Token": response.json()["csrf"]}


def change(client, headers, revision, **command):
    return client.post(API + "/draft/changes", json={"expected_revision": revision, **command}, headers=headers)


def test_draft_revision_csv_undo_and_auth():
    with TestClient(app) as client:
        assert client.get(API + "/ready").json() == {"status": "ready"}
        assert client.get(API + "/draft").status_code == 401
        headers = register(client, "tester")
        draft = client.get(API + "/draft").json()
        assert change(client, {}, 0, action="sample").status_code == 403
        assert client.get(API + "/admin/overview").status_code == 403
        cookie = dict(client.cookies)
        with TestClient(app, cookies=cookie) as second_tab, ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(change, client, headers, 0, action="settings",
                                week_start=draft["settings"]["week_start"], sleep_start="23:30", sleep_end="05:00")
            second = pool.submit(change, second_tab, headers, 0, action="sample")
            assert sorted((first.result().status_code, second.result().status_code)) == [200, 409]
        assert change(client, headers, 1, action="undo").json()["fixed_tasks"] == []

        csv = ("task_type,name,repeat,one_off_date,start,end\n"
               "fixed,Đọc sách,mon,,08:00,09:00\nfixed,Giờ sai,tue,,12:99,13:00\n").encode("utf-8-sig")
        preview = client.post(API + "/draft/imports/preview", headers=headers, content=csv).json()
        assert preview["valid"] == 1
        assert preview["rows"][1]["line"] == 3
        result = client.post(API + "/draft/imports", params={"expected_revision": preview["revision"]},
                             headers=headers, content=csv)
        assert result.status_code == 200, result.text
        draft = result.json()
        assert len(draft["fixed_tasks"]) == 1
        assert client.get(API + "/draft/export").content.startswith(b"\xef\xbb\xbf")
        event = next(event for event in client.get(API + "/draft/preview").json()["events"] if event.get("editable"))
        moved = change(client, headers, draft["revision"], action="move", task_id=draft["fixed_tasks"][0]["id"],
                       old_start=event["start"], new_start=event["start"].replace("08:00", "08:20"))
        assert moved.json()["fixed_tasks"][0]["start"] == "08:20", moved.text
        undo_move = change(client, headers, moved.json()["revision"], action="undo").json()
        assert undo_move["fixed_tasks"][0]["start"] == "08:00"
        assert undo_move["can_undo"]
        assert change(client, headers, undo_move["revision"], action="undo").json()["fixed_tasks"] == []
        assert client.post(API + "/auth/logout", headers=headers).status_code == 204
        with TestClient(app, cookies=cookie) as stale:
            assert stale.get(API + "/auth/me").status_code == 401


def test_conflict_and_rating_survive_restart():
    with TestClient(app) as client:
        headers = register(client, "conflict")
        draft = client.get(API + "/draft").json()
        week = date.fromisoformat(draft["settings"]["week_start"]) + timedelta(days=7)
        assert change(client, headers, 0, action="settings", week_start=week.isoformat(),
                      sleep_start="23:00", sleep_end="05:00").status_code == 200
        task = change(client, headers, 1, action="task", fixed=False, fields={
            "name": "Việc sát giờ", "deadline": f"{week}T05:15", "remaining_min": 60,
            "chunk_min": 60, "chunk_max": 60, "buffer_min": 0, "mandatory": "Có",
        })
        assert task.status_code == 200, task.text
        request = {"expected_revision": 2, "operation_id": str(uuid4())}
        planned = client.post(API + "/plans", headers=headers, json=request)
        assert planned.status_code == 201, planned.text
        plan = planned.json()
        assert client.post(API + "/plans", headers=headers, json=request).json()["id"] == plan["id"]
        assert plan["status"] == "NOT_FOUND"
        path = f"{API}/plans/{plan['id']}"
        target = plan["unscheduled"][0]["id"]
        analysis_request = {"task_id": target, "expected_version": 0}
        analysis = client.post(path + "/conflicts", headers=headers, json=analysis_request)
        assert analysis.status_code == 200, analysis.text
        assert len(analysis.json()["reports"][target]["options"]) == 3
        cookie = dict(client.cookies)

    with TestClient(app, cookies=cookie) as client:
        assert target in client.get(API + "/plans/latest").json()["reports"]
        apply_request = {**analysis_request, "option_id": 1, "operation_id": str(uuid4())}
        applied = client.post(path + "/apply", headers=headers, json=apply_request)
        assert applied.status_code == 200, applied.text
        assert applied.json()["version"] == 1
        assert not applied.json()["unscheduled"]
        assert client.post(path + "/apply", headers=headers, json=apply_request).json()["version"] == 1
        assert client.post(path + "/apply", headers=headers,
                           json={**apply_request, "operation_id": str(uuid4())}).status_code == 409
        history = client.get(API + "/history").json()
        assert len(history) == 1
        assert client.get(f"{API}/history/{history[0]['id']}").status_code == 200
        payload = {"expected_version": 1}
        key = client.post(path + "/finalize", headers=headers, json=payload).json()["schedule_key"]
        final_download = client.post(path + "/download", headers=headers, json=payload)
        assert final_download.json()["schedule_key"] == key
        with connect(db_path()) as conn:
            assert conn.execute("SELECT COUNT(*) FROM finalized_schedules").fetchone()[0] == 1

        ratings_path = f"{API}/ratings/{key}"
        rating = {
            "criteria": {item["key"]: {"importance": 4, "satisfaction": None} for item in rating_schema.CRITERIA},
            "tradeoffs": {item["key"]: 0 for item in rating_schema.TRADEOFFS}, "overall": 4,
            "nps": 8, "adoption": rating_schema.ADOPTION_OPTIONS[0], "vs_manual": None,
            "conflict_clarity": 4, "problems": [], "comment_good": "Dễ dùng",
        }
        assert client.put(ratings_path, headers=headers, json=rating).status_code == 200
        updated = client.put(ratings_path, headers=headers, json={**rating, "overall": 5})
        assert updated.json()["rating"]["overall"] == 5
        with TestClient(app) as someone_else:
            register(someone_else, "different")
            assert someone_else.get(path).status_code == 404
            assert someone_else.get(ratings_path).status_code == 404
            assert someone_else.get(API + "/history").json() == []

    with TestClient(app) as admin:
        response = admin.post(API + "/auth/login", json={"username": "admin", "password": PASSWORD})
        assert response.status_code == 200
        overview = admin.get(API + "/admin/overview").json()
        assert overview["kpi"]["ratings_total"] == 1
        assert "password_hash" not in overview["users"][0]
        assert admin.get(API + "/admin/ratings.csv", params={"score": 5}).content.startswith(b"\xef\xbb\xbf")
        assert b"conflict" not in admin.get(API + "/admin/ratings.csv", params={"score": 4}).content


def test_react_csv_template_and_recurring_calendar_colors():
    with TestClient(app) as client:
        headers = register(client, "calendar")
        draft = client.get(API + "/draft", headers={"Accept-Language": "en"}).json()
        assert draft["issues"][0]["message"] == "Please enter at least one task."
        template = client.get(API + "/draft/example?lang=en")
        assert template.content.startswith(b"\xef\xbb\xbf")
        assert b"Class" in template.content
        imported = client.post(API + "/draft/imports", params={"expected_revision": draft["revision"]},
                               headers=headers, content=template.content).json()
        original = imported["fixed_tasks"][0]
        result = change(client, headers, imported["revision"], action="task", fixed=True, task_id=original["id"],
                        fields=original, color="#182337")
        assert result.status_code == 200, result.text
        preview = client.get(API + "/draft/preview").json()
        events = [event for event in preview["events"] if event.get("editable")]
        assert len(events) == len({event["id"] for event in events}) == 2
        assert {event["textColor"] for event in events} == {"#ffffff"}
        assert all(event["extendedProps"]["task_id"] == original["id"] for event in events)
        snapshot = client.get(API + "/draft/snapshot").json()
        assert "color" not in snapshot["fixed_tasks"][0]
        assert snapshot["fixed_tasks"][0]["after_min"] == 10


def test_login_requires_account_to_match_selected_role():
    with TestClient(app) as client:
        register(client, "planner")
        for username, role in (("admin", "user"), ("planner", "admin")):
            denied = client.post(API + "/auth/login", json={
                "username": username, "password": PASSWORD, "role": role,
            })
            assert denied.status_code == 401
            assert client.get(API + "/auth/me").json()["user"]["username"] == "planner"
        planner = client.post(API + "/auth/login", json={
            "username": "planner", "password": PASSWORD, "role": "user",
        })
        assert planner.json()["user"]["role"] == "user"
        assert client.get(API + "/admin/overview").status_code == 403
        admin = client.post(API + "/auth/login", json={
            "username": "admin", "password": PASSWORD, "role": "admin",
        })
        assert admin.json()["user"]["role"] == "admin"
        assert client.get(API + "/admin/overview").status_code == 200
        assert client.get(API + "/draft").status_code == 403


def test_legacy_draft_and_color_import(tmp_path):
    source_dir = tmp_path / "old"
    source = source_dir / "portal.db"
    auth.init_portal(source)
    user, _ = auth.register_user("olduser", "Người dùng cũ", None, auth.USER_GROUPS[0],
                                 PASSWORD, PASSWORD, True, source)
    user_dir = source_dir / "users" / f"u{user.id}"
    draft_path = user_dir / "schedule_input_draft.json"
    monday = "2026-10-19"
    user_dir.mkdir(parents=True)
    draft_path.write_text(json.dumps({
        "schema_version": 1, "settings": {"week_start": monday, "sleep": {"start": "23:00", "end": "05:00"}},
        "fixed_tasks": [{"id": "ft_old", "name": "Old task", "repeat_days": ["mon"], "start": "08:00", "end": "09:00"}],
        "deadline_tasks": [{"id": "dt_old", "name": "Old deadline", "importance": 8,
                            "deadline": f"{monday}T19:00", "remaining_min": 60}],
    }), encoding="utf-8")
    (user_dir / "calendar_colors.json").write_text('{"ft_old":"#187463"}', encoding="utf-8")
    legacy_plan = {
        "id": "old-schedule", "week_start": monday, "version": 2, "complete": True,
        "saved_at": "2026-10-19T01:00:00+00:00", "context": {"tasks": [], "fixed_tasks": [], "active_windows": []},
        "result": {"status": "FEASIBLE", "unscheduled": {}, "chunks": []},
    }
    (user_dir / "schedule_history.json").write_text(
        json.dumps({"schema_version": 1, "schedules": [legacy_plan]}), encoding="utf-8",
    )
    original = draft_path.read_bytes()
    destination = db_path()
    assert migrate(source, source_dir, destination)["draft_candidates"] == 1
    assert not destination.exists()
    imported = migrate(source, source_dir, destination, apply=True)
    assert imported["drafts_imported"] == imported["history_imported"] == 1
    retried = migrate(source, source_dir, destination, apply=True)
    assert retried["drafts_imported"] == retried["history_imported"] == 0
    assert draft_path.read_bytes() == original
    with TestClient(app) as client:
        assert client.post(API + "/auth/login", json={"username": "olduser", "password": PASSWORD}).status_code == 200
        draft = client.get(API + "/draft").json()
        assert draft["settings"]["week_start"] == monday
        assert draft["deadline_tasks"][0]["importance"] == "3"
        assert draft["colors"] == {"ft_old": "#187463"}
        assert client.get(API + "/history/old-schedule").json()["record"]["version"] == 2
