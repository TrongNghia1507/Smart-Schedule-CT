import pytest

from user_portal import auth, repository
from user_portal.metrics import compute_schedule_metrics, criterion_facts, schedule_key
from user_portal.rating_schema import CRITERIA, TRADEOFFS


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "portal.db"
    auth.init_portal(path)
    return path


def make_user(db, name="anna", password="matkhau1"):
    user, errors = auth.register_user(name, "Nguyễn Văn An", "", "Sinh viên", password, password, True, db)
    assert not errors, errors
    return user


def test_admin_default_password_and_idempotent_seed(db):
    auth.init_portal(db)  # gọi lại không tạo admin thứ hai
    user, error = auth.login_admin("123", db)
    assert error is None and user.is_admin
    assert auth.login_admin("sai", db)[1] is not None


def test_register_validation_and_duplicates(db):
    make_user(db)
    _, errors = auth.register_user("anna", "Người khác", "", "Khác", "abcdef", "abcdef", True, db)
    assert any("đã tồn tại" in e for e in errors)
    _, errors = auth.register_user("admin", "X Y", "", "Khác", "abcdef", "abcdef", True, db)
    assert errors
    _, errors = auth.register_user("Bad Name!", "X", "bad", "Khác", "123", "124", False, db)
    assert len(errors) >= 4
    # tên đăng nhập không phân biệt hoa/thường
    assert auth.login_user("ANNA", "matkhau1", db)[0].username == "anna"


def test_user_cannot_login_as_admin_and_reverse(db):
    make_user(db)
    assert auth.login_user("admin", "123", db)[0] is None
    assert auth.login_admin("matkhau1", db)[0] is None


def test_lockout_after_repeated_failures(db):
    make_user(db)
    for _ in range(auth.MAX_FAILED_ATTEMPTS):
        assert auth.login_user("anna", "sai-mat-khau", db)[0] is None
    user, error = auth.login_user("anna", "matkhau1", db)
    assert user is None and "quá nhiều" in error


def test_passwords_are_hashed(db):
    make_user(db)
    with auth.connect(db) as conn:
        stored = conn.execute("SELECT password_hash FROM users WHERE username='anna'").fetchone()[0]
    assert stored.startswith("scrypt$") and "matkhau1" not in stored


def test_change_admin_password(db):
    assert auth.change_admin_password("sai", "newpass1", "newpass1", db)
    assert auth.change_admin_password("123", "newpass1", "newpass1", db) is None
    assert auth.login_admin("123", db)[0] is None
    assert auth.login_admin("newpass1", db)[0].is_admin


CONTEXT = {
    "schedule_version": 1,
    "tasks": [
        {"id": "A", "name": "A", "mandatory": True, "importance": 3, "remaining_min": 120, "deadline": 1440 + 600},
        {"id": "B", "name": "B", "mandatory": False, "importance": 1, "remaining_min": 60, "deadline": 3000},
        {"id": "C", "name": "C", "mandatory": False, "importance": 2, "remaining_min": 90, "deadline": 3000},
    ],
    "fixed_tasks": [{"id": "F", "name": "F", "interval": {"start": 540, "end": 600}}],
    "active_windows": [{"start": 450, "end": 1320}, {"start": 1890, "end": 2760}],
}
RESULT = {
    "status": "FEASIBLE", "solver_status": "OPTIMAL",
    "chunks": [
        {"task_id": "A", "start": 600, "end": 660, "buffer_end": 675},
        {"task_id": "A", "start": 1300, "end": 1360, "buffer_end": 1375},  # 21:40 -> 22:40: khuya
        {"task_id": "B", "start": 1900, "end": 1960, "buffer_end": 1975},
    ],
    "unscheduled": {"C": 90},
}
APPLIED = [{"option_id": 2, "duration_min": 120,
            "action_payload": {"operation": "COMPRESS_TASK", "old_duration": 180, "new_duration": 120}}]


def test_metrics_values():
    m = compute_schedule_metrics(CONTEXT, RESULT, APPLIED)
    assert (m["tasks_total"], m["tasks_fully_placed"], m["tasks_unplaced"]) == (3, 2, 1)
    assert m["coverage_task_ratio"] == pytest.approx(2 / 3, abs=1e-3)
    assert m["placed_minutes"] == 180 and m["required_minutes"] == 270
    assert m["priority_weighted_ratio"] == pytest.approx(4 / 6, abs=1e-3)  # (3 + 1) / (3 + 1 + 2)
    assert m["mandatory_placed"] == 1 and m["high_importance_placed"] == 1
    assert m["on_time_ratio"] == 1.0 and m["min_slack_min"] == 2040 - 1360
    assert m["chunks_total"] == 3 and m["tasks_split"] == 1 and m["avg_chunk_min"] == 60
    assert m["reduced_tasks"] == 1 and m["reduced_minutes"] == 60
    assert m["complete"] is False and m["proven_optimal"] is True
    assert m["max_day_minutes"] == 120


def test_metrics_odd_hours_exact():
    # 21:00 = phút 1260 → chunk 1300–1360 nằm trọn trong khung sau 21:00
    m = compute_schedule_metrics(CONTEXT, RESULT, APPLIED)
    assert m["odd_hour_minutes"] == 60


def test_metrics_empty_result_does_not_crash():
    m = compute_schedule_metrics(CONTEXT, {"status": "NOT_FOUND", "chunks": [], "unscheduled": {"A": 120, "B": 60, "C": 90}})
    assert m["tasks_fully_placed"] == 0 and m["chunks_total"] == 0 and m["on_time_ratio"] is None
    assert set(criterion_facts(m)) == {c["key"] for c in CRITERIA}


def test_schedule_key_stable_and_sensitive():
    a = schedule_key(CONTEXT, RESULT, "2026-11-30")
    assert a == schedule_key(CONTEXT, RESULT, "2026-11-30")
    changed = {**RESULT, "chunks": RESULT["chunks"][:-1]}
    assert a != schedule_key(CONTEXT, changed, "2026-11-30")
    assert a != schedule_key(CONTEXT, RESULT, "2026-12-07")


def answers(overall=4, sat=4, imp=5, trade=0):
    return {
        "criteria": {c["key"]: {"satisfaction": sat, "importance": imp} for c in CRITERIA},
        "tradeoffs": {t["key"]: trade for t in TRADEOFFS},
        "overall": overall, "nps": 9, "adoption": "Dùng nguyên như vậy", "vs_manual": 4,
        "conflict_clarity": 3, "problems": ["Quá nhiều phiên nhỏ lẻ"],
        "comment_good": "ổn", "comment_improve": "",
    }


def test_rating_upsert_and_overview(db):
    u1, u2 = make_user(db, "anna"), make_user(db, "binh")
    metrics = compute_schedule_metrics(CONTEXT, RESULT, APPLIED)
    key = schedule_key(CONTEXT, RESULT, "2026-11-30")
    for user in (u1, u2):
        repository.record_finalized(user.id, key, "2026-11-30", False, True, db)
    repository.save_rating(u1.id, key, "2026-11-30", answers(overall=5), metrics, db)
    repository.save_rating(u2.id, key, "2026-11-30", answers(overall=2, sat=2, trade=-2), metrics, db)
    # chấm lại cùng lịch → cập nhật, không thêm dòng
    repository.save_rating(u2.id, key, "2026-11-30", answers(overall=3, sat=2, trade=-2), metrics, db)

    data = repository.overview(db)
    k = data["kpi"]
    assert k["users_total"] == 2 and k["ratings_total"] == 2 and k["finalized_total"] == 2
    assert k["overall_mean"] == 4.0 and k["response_rate"] == 1.0
    assert data["overall_distribution"][5] == 1 and data["overall_distribution"][3] == 1
    coverage = next(c for c in data["criteria"] if c["key"] == "coverage")
    assert coverage["satisfaction"] == 3.0 and coverage["importance"] == 5.0
    assert coverage["priority_gap"] == pytest.approx((5 * 1 + 5 * 3) / 2)
    assert data["tradeoffs"][0]["toward_a"] == 1 and data["tradeoffs"][0]["balanced"] == 1
    assert data["problems"]["Quá nhiều phiên nhỏ lẻ"] == 2
    assert k["nps"] == 100  # cả hai chấm 9


def test_overview_empty_db(db):
    data = repository.overview(db)
    assert data["kpi"]["users_total"] == 0 and data["kpi"]["nps"] is None and data["kpi"]["overall_mean"] is None
