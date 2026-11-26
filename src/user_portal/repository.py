"""Ghi và đọc dữ liệu đánh giá, thống kê cho trang admin."""
from __future__ import annotations

import json
from collections import defaultdict
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from statistics import mean, pstdev

from .db import connect, utc_now
from .rating_schema import CRITERIA, TRADEOFFS


def record_finalized(user_id, key, week_start, complete, used_conflict, path=None, *, conn=None) -> None:
    with (nullcontext(conn) if conn is not None else connect(path)) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO finalized_schedules(user_id, schedule_key, week_start, complete, "
            "used_conflict_options, at) VALUES (?,?,?,?,?,?)",
            (user_id, key, week_start, int(complete), int(used_conflict), utc_now()),
        )


def get_rating(user_id, key, path=None):
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM ratings WHERE user_id=? AND schedule_key=?", (user_id, key)).fetchone()
        return dict(row) if row else None


def save_rating(user_id, key, week_start, answers: dict, metrics: dict, path=None) -> None:
    """Thêm mới hoặc cập nhật đánh giá của cùng người dùng cho cùng một lịch."""
    stamp = utc_now()
    values = (
        answers["overall"], answers.get("nps"), answers.get("adoption"), answers.get("vs_manual"),
        answers.get("conflict_clarity"),
        json.dumps(answers["criteria"], ensure_ascii=False),
        json.dumps(answers["tradeoffs"], ensure_ascii=False),
        json.dumps(answers["problems"], ensure_ascii=False),
        json.dumps(metrics, ensure_ascii=False),
        (answers.get("comment_good") or "").strip()[:600],
        (answers.get("comment_improve") or "").strip()[:600],
    )
    with connect(path) as conn:
        conn.execute(
            """INSERT INTO ratings(user_id, schedule_key, week_start, created_at, updated_at, overall, nps,
               adoption, vs_manual, conflict_clarity, criteria_json, tradeoffs_json, problems_json,
               metrics_json, comment_good, comment_improve) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(user_id, schedule_key) DO UPDATE SET
               updated_at=excluded.updated_at, overall=excluded.overall, nps=excluded.nps,
               adoption=excluded.adoption, vs_manual=excluded.vs_manual, conflict_clarity=excluded.conflict_clarity,
               criteria_json=excluded.criteria_json, tradeoffs_json=excluded.tradeoffs_json,
               problems_json=excluded.problems_json, metrics_json=excluded.metrics_json,
               comment_good=excluded.comment_good, comment_improve=excluded.comment_improve""",
            (user_id, key, week_start, stamp, stamp, *values),
        )


def _days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def _nps(scores) -> float | None:
    scores = [s for s in scores if s is not None]
    if not scores:
        return None
    promoters = sum(1 for s in scores if s >= 9)
    detractors = sum(1 for s in scores if s <= 6)
    return round((promoters - detractors) / len(scores) * 100)


def overview(path=None) -> dict:
    """Toàn bộ số liệu cho trang admin, tính một lần."""
    with connect(path) as conn:
        users = [dict(r) for r in conn.execute("SELECT * FROM users WHERE role='user' ORDER BY created_at DESC")]
        ratings = [dict(r) for r in conn.execute(
            "SELECT r.*, u.username, u.full_name, u.user_group FROM ratings r "
            "JOIN users u ON u.id=r.user_id ORDER BY r.updated_at DESC")]
        finalized = [dict(r) for r in conn.execute("SELECT * FROM finalized_schedules")]
        logins = [dict(r) for r in conn.execute(
            "SELECT le.at, le.user_id FROM login_events le JOIN users u ON u.id=le.user_id WHERE u.role='user'")]

    for rating in ratings:
        rating["criteria"] = json.loads(rating["criteria_json"])
        rating["tradeoffs"] = json.loads(rating["tradeoffs_json"])
        rating["problems"] = json.loads(rating["problems_json"])
        rating["metrics"] = json.loads(rating["metrics_json"])

    week, month = _days_ago(7), _days_ago(30)
    active_7d = {e["user_id"] for e in logins if e["at"] >= week}
    rated_users = {r["user_id"] for r in ratings}

    criteria_stats = []
    for item in CRITERIA:
        sat = [r["criteria"].get(item["key"], {}).get("satisfaction") for r in ratings]
        imp = [r["criteria"].get(item["key"], {}).get("importance") for r in ratings]
        sat_values = [s for s in sat if s is not None]
        imp_values = [i for i in imp if i is not None]
        weighted_pairs = [(s, i) for s, i in zip(sat, imp) if s is not None and i is not None]
        criteria_stats.append({
            "key": item["key"], "title": item["title"], "short": item["short"],
            "n": len(sat_values),
            "satisfaction": round(mean(sat_values), 2) if sat_values else None,
            "importance": round(mean(imp_values), 2) if imp_values else None,
            "std": round(pstdev(sat_values), 2) if len(sat_values) > 1 else 0.0,
            "low_share": round(sum(1 for s in sat_values if s <= 2) / len(sat_values), 3) if sat_values else None,
            # Khoảng cách ưu tiên: quan trọng cao mà hài lòng thấp thì số này lớn.
            "priority_gap": round(mean([i * (5 - s) for s, i in weighted_pairs]), 2) if weighted_pairs else None,
        })

    tradeoff_stats = []
    for item in TRADEOFFS:
        votes = [r["tradeoffs"].get(item["key"]) for r in ratings]
        votes = [v for v in votes if v is not None]
        tradeoff_stats.append({
            **item, "n": len(votes),
            "toward_a": sum(1 for v in votes if v < 0),
            "balanced": sum(1 for v in votes if v == 0),
            "toward_b": sum(1 for v in votes if v > 0),
            "mean": round(mean(votes), 2) if votes else None,
        })

    problems = defaultdict(int)
    for rating in ratings:
        for problem in rating["problems"]:
            problems[problem] += 1

    overall = [r["overall"] for r in ratings]
    adoption = defaultdict(int)
    for rating in ratings:
        if rating["adoption"]:
            adoption[rating["adoption"]] += 1

    def metric_avg(name, keep=lambda v: v is not None):
        values = [r["metrics"].get(name) for r in ratings]
        values = [v for v in values if keep(v)]
        return round(mean(values), 3) if values else None

    return {
        "users": users, "ratings": ratings, "finalized": finalized, "logins": logins,
        "kpi": {
            "users_total": len(users),
            "users_new_7d": sum(1 for u in users if u["created_at"] >= week),
            "users_active_7d": len(active_7d),
            "logins_30d": sum(1 for e in logins if e["at"] >= month),
            "finalized_total": len(finalized),
            "finalized_complete": sum(1 for f in finalized if f["complete"]),
            "finalized_with_conflict": sum(1 for f in finalized if f["used_conflict_options"]),
            "ratings_total": len(ratings),
            "raters": len(rated_users),
            "response_rate": round(len(ratings) / len(finalized), 3) if finalized else None,
            "overall_mean": round(mean(overall), 2) if overall else None,
            "overall_std": round(pstdev(overall), 2) if len(overall) > 1 else 0.0,
            "nps": _nps([r["nps"] for r in ratings]),
            "accept_rate": round(sum(1 for r in ratings if r["adoption"] in
                                     ("Dùng nguyên như vậy", "Dùng sau khi chỉnh nhỏ (1–2 chỗ)")) / len(ratings), 3)
            if ratings else None,
        },
        "criteria": criteria_stats,
        "tradeoffs": tradeoff_stats,
        "problems": dict(sorted(problems.items(), key=lambda kv: -kv[1])),
        "adoption": dict(adoption),
        "overall_distribution": {s: overall.count(s) for s in range(1, 6)},
        "metric_means": {
            "coverage_task_ratio": metric_avg("coverage_task_ratio"),
            "priority_weighted_ratio": metric_avg("priority_weighted_ratio"),
            "avg_chunk_min": metric_avg("avg_chunk_min"),
            "max_day_minutes": metric_avg("max_day_minutes"),
            "utilization_ratio": metric_avg("utilization_ratio"),
        },
    }
