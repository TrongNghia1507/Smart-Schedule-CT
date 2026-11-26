"""Đánh giá lịch vừa chốt (bảng feedbacks - 4 phần A, B, C, D) và xuất CSV/thống kê cho Admin.

Hỗ trợ nhận cả mã chuẩn tiếng Anh lẫn nhãn tiếng Việt trực tiếp từ giao diện Streamlit để nhóm
làm Frontend gọi cực gọn mà không sợ lệch chuỗi.
"""
from __future__ import annotations

import csv
import hmac
import io
import json

from .config import get_backend_settings
from .db import db_readonly, db_transaction
from .errors import AuthError, FeedbackInvalidError, NotFoundError

CRITERIA_KEYS = (
    "coverage",     # 1. Hoàn thành đủ công việc (Độ phủ)
    "priority",     # 2. Ưu tiên việc quan trọng (Ưu tiên)
    "deadline",     # 3. Đúng hạn và có dư địa (Đúng hạn)
    "continuity",   # 4. Liền mạch, ít bị chia nhỏ (Liền mạch)
    "balance",      # 5. Cân bằng khối lượng và nghỉ ngơi (Cân bằng)
    "constraints",  # 6. Giữ nguyên ràng buộc cá nhân (Giữ ràng buộc)
    "feasibility",  # 7. Khả thi khi thực hiện (Khả thi)
)

TRADEOFF_LABELS = {
    "Hẳn A": 1,
    "Hơi nghiêng A": 2,
    "Cân bằng": 3,
    "Hơi nghiêng B": 4,
    "Hẳn B": 5,
}

USAGE_INTENT_MAP = {
    "use_as_is": "use_as_is",
    "Dùng nguyên như vậy": "use_as_is",
    "minor_edits": "minor_edits",
    "Dùng sau khi chỉnh nhỏ (1–2 chỗ)": "minor_edits",
    "Dùng sau khi chỉnh nhỏ (1-2 chỗ)": "minor_edits",
    "major_edits": "major_edits",
    "Phải chỉnh nhiều (từ 3 chỗ)": "major_edits",
    "wont_use": "wont_use",
    "Sẽ không dùng lịch này": "wont_use",
}

VS_SELF_MAP = {
    "much_worse": "much_worse",
    "Kém hơn nhiều": "much_worse",
    "slightly_worse": "slightly_worse",
    "Kém hơn một chút": "slightly_worse",
    "similar": "similar",
    "Tương đương": "similar",
    "slightly_better": "slightly_better",
    "Tốt hơn một chút": "slightly_better",
    "much_better": "much_better",
    "Tốt hơn nhiều": "much_better",
    "never_self_scheduled": "never_self_scheduled",
    "Tôi chưa từng tự xếp lịch tuần": "never_self_scheduled",
}

ISSUE_TAG_MAP = {
    "late_important_tasks": "late_important_tasks",
    "Việc quan trọng bị xếp muộn": "late_important_tasks",
    "too_many_small_chunks": "too_many_small_chunks",
    "Quá nhiều phiên nhỏ lẻ": "too_many_small_chunks",
    "overloaded_days_lack_rest": "overloaded_days_lack_rest",
    "Có ngày quá dày, thiếu nghỉ": "overloaded_days_lack_rest",
    "too_late_or_too_early": "too_late_or_too_early",
    "Phải làm quá khuya hoặc quá sớm": "too_late_or_too_early",
    "unwanted_constraint_changes": "unwanted_constraint_changes",
    "Ràng buộc cá nhân bị thay đổi ngoài ý muốn": "unwanted_constraint_changes",
    "dropped_or_reduced_tasks": "dropped_or_reduced_tasks",
    "Có việc bị bỏ hoặc bị giảm thời lượng": "dropped_or_reduced_tasks",
    "awkward_gaps": "awkward_gaps",
    "Khoảng trống giữa các việc kém hợp lý": "awkward_gaps",
    "hard_to_understand_why": "hard_to_understand_why",
    "Khó hiểu vì sao lịch được xếp như vậy": "hard_to_understand_why",
    "no_significant_issues": "no_significant_issues",
    "Không có vấn đề đáng kể": "no_significant_issues",
}

REPORT_SQL = """
SELECT f.id AS feedback_id, f.created_at, f.updated_at,
       u.username, u.role_group,
       s.id AS schedule_id, s.week_start, s.schedule_version, s.creation_source,
       s.applied_option_id, s.status, s.proven_optimal,
       s.total_tasks, s.scheduled_tasks, s.unscheduled_tasks,
       f.sat_coverage, f.imp_coverage,
       f.sat_priority, f.imp_priority,
       f.sat_deadline, f.imp_deadline,
       f.sat_continuity, f.imp_continuity,
       f.sat_balance, f.imp_balance,
       f.sat_constraints, f.imp_constraints,
       f.sat_feasibility, f.imp_feasibility,
       f.tradeoff_pair_1, f.tradeoff_pair_2, f.tradeoff_pair_3,
       f.tradeoff_pair_4, f.tradeoff_pair_5,
       f.overall_satisfaction, f.usage_intent, f.vs_self_scheduling,
       f.nps_score, f.conflict_clarity_score,
       f.reported_issues_json, f.best_aspect, f.needs_improvement,
       f.system_metrics_json
FROM feedbacks f
JOIN users u     ON u.id = f.user_id
JOIN schedules s ON s.id = f.schedule_id
ORDER BY f.created_at, f.id
"""


def _parse_int_range(value, lo: int, hi: int, field_name: str, *, allow_none: bool = False):
    if value is None or (isinstance(value, str) and value.strip().lower() in ("", "không áp dụng", "na", "n/a")):
        if allow_none:
            return None
        raise FeedbackInvalidError(f"Vui lòng trả lời mục '{field_name}'.")
    if isinstance(value, str):
        # Cho phép chuỗi dạng "4 - Hài lòng" hoặc "4 · Hài lòng"
        head = value.strip().split()[0].rstrip("-·.")
        if head.isdigit():
            value = int(head)
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise FeedbackInvalidError(f"Giá trị '{field_name}' phải là số nguyên từ {lo} đến {hi}.")
    return value


def _parse_tradeoff(value, index: int) -> int:
    if isinstance(value, str) and value.strip() in TRADEOFF_LABELS:
        return TRADEOFF_LABELS[value.strip()]
    return _parse_int_range(value, 1, 5, f"Cặp đánh đổi {index}")


def _parse_enum(value, mapping: dict[str, str], field_name: str) -> str:
    key = (value or "").strip() if isinstance(value, str) else ""
    if key not in mapping:
        raise FeedbackInvalidError(f"Lựa chọn không hợp lệ cho mục '{field_name}'.")
    return mapping[key]


def _parse_issues(values) -> list[str]:
    if not isinstance(values, (list, tuple, set)) or not values:
        raise FeedbackInvalidError(
            "Vui lòng chọn ít nhất một mục ở phần 'Lịch này có vấn đề nào sau đây?' "
            "(hoặc chọn 'Không có vấn đề đáng kể')."
        )
    normalized = []
    for raw in values:
        key = str(raw).strip()
        if key not in ISSUE_TAG_MAP:
            raise FeedbackInvalidError(f"Tag vấn đề không hợp lệ: {key!r}")
        code = ISSUE_TAG_MAP[key]
        if code not in normalized:
            normalized.append(code)
    if "no_significant_issues" in normalized and len(normalized) > 1:
        normalized = [c for c in normalized if c != "no_significant_issues"]
    return normalized


def _weighted_satisfaction(row: dict) -> float | None:
    """Điểm hài lòng có trọng số theo mức độ quan trọng của từng cá nhân."""
    num, den = 0, 0
    for key in CRITERIA_KEYS:
        sat = row.get(f"sat_{key}")
        imp = row.get(f"imp_{key}")
        if sat is not None and imp is not None:
            num += int(sat) * int(imp)
            den += int(imp)
    return round(num / den, 2) if den > 0 else None


def submit_feedback(user_id: int, schedule_id: int, payload: dict) -> int:
    """Lưu hoặc cập nhật biểu mẫu đánh giá 4 phần (A, B, C, D) cho (user_id, schedule_id).

    ``payload`` nhận dict có cấu trúc::

        {
            # Phần A - 7 tiêu chí (sat_* có thể là 1..5 hoặc None/"Không áp dụng"; imp_* bắt buộc 1..5)
            "criteria": {
                "coverage":    {"satisfaction": 5, "importance": 5},
                "priority":    {"satisfaction": 5, "importance": 5},
                "deadline":    {"satisfaction": 4, "importance": 4},
                "continuity":  {"satisfaction": 4, "importance": 3},
                "balance":     {"satisfaction": 3, "importance": 4},
                "constraints": {"satisfaction": None, "importance": 3},
                "feasibility": {"satisfaction": 4, "importance": 5},
            },
            # Phần B - 5 cặp đánh đổi (nhận 1..5 hoặc nhãn "Hẳn A".."Hẳn B"): list 5 phần tử hoặc dict
            "tradeoffs": [2, 3, 4, 2, 3],
            # Phần C - Đánh giá chung (nhận mã chuẩn hoặc nhãn tiếng Việt trên form)
            "overall_satisfaction": 4,
            "usage_intent": "minor_edits",
            "vs_self_scheduling": "slightly_better",
            "nps_score": 8,
            "conflict_clarity_score": 4,   # None nếu lịch không có xung đột
            # Phần D - Vấn đề & góp ý
            "reported_issues": ["too_many_small_chunks"],
            "best_aspect": "Xếp đủ toàn bộ việc quan trọng.",
            "needs_improvement": "Buổi tối hơi dày.",
            # Tùy chọn: snapshot các con số "Hệ thống đo được"
            "system_metrics": {"scheduled_ratio": "8/8", "on_time_pct": 100, "chunks": 29},
        }
    """
    user_id = int(user_id)
    schedule_id = int(schedule_id)
    criteria_in = payload.get("criteria") or {}

    crit_vals: dict[str, int | None] = {}
    for key in CRITERIA_KEYS:
        item = criteria_in.get(key) if isinstance(criteria_in, dict) else None
        sat_raw = item.get("satisfaction") if isinstance(item, dict) else payload.get(f"sat_{key}")
        imp_raw = item.get("importance") if isinstance(item, dict) else payload.get(f"imp_{key}")
        crit_vals[f"sat_{key}"] = _parse_int_range(sat_raw, 1, 5, f"Hài lòng ({key})", allow_none=True)
        crit_vals[f"imp_{key}"] = _parse_int_range(imp_raw, 1, 5, f"Quan trọng ({key})", allow_none=False)

    raw_tradeoffs = payload.get("tradeoffs")
    tradeoff_vals: list[int] = []
    for idx in range(1, 6):
        if isinstance(raw_tradeoffs, (list, tuple)) and len(raw_tradeoffs) == 5:
            val = raw_tradeoffs[idx - 1]
        elif isinstance(raw_tradeoffs, dict):
            val = raw_tradeoffs.get(idx, raw_tradeoffs.get(str(idx), raw_tradeoffs.get(f"pair_{idx}")))
        else:
            val = payload.get(f"tradeoff_pair_{idx}")
        tradeoff_vals.append(_parse_tradeoff(val, idx))

    overall = _parse_int_range(payload.get("overall_satisfaction"), 1, 5, "Mức hài lòng tổng thể")
    usage = _parse_enum(payload.get("usage_intent"), USAGE_INTENT_MAP, "Bạn sẽ dùng lịch này như thế nào")
    vs_self = _parse_enum(payload.get("vs_self_scheduling"), VS_SELF_MAP, "So với tự xếp lịch thường ngày")
    nps = _parse_int_range(payload.get("nps_score"), 0, 10, "Khả năng giới thiệu (NPS 0–10)")
    conflict_clarity = _parse_int_range(
        payload.get("conflict_clarity_score"), 1, 5, "Đánh giá phương án xung đột", allow_none=True
    )

    issues = _parse_issues(payload.get("reported_issues"))
    best_aspect = (payload.get("best_aspect") or "").strip()[:5000] or None
    needs_improvement = (payload.get("needs_improvement") or "").strip()[:5000] or None
    sys_metrics = payload.get("system_metrics")
    sys_metrics_json = json.dumps(sys_metrics, ensure_ascii=False) if sys_metrics is not None else None

    columns = [
        "user_id", "schedule_id", "history_id", "system_metrics_json",
        "sat_coverage", "imp_coverage", "sat_priority", "imp_priority",
        "sat_deadline", "imp_deadline", "sat_continuity", "imp_continuity",
        "sat_balance", "imp_balance", "sat_constraints", "imp_constraints",
        "sat_feasibility", "imp_feasibility",
        "tradeoff_pair_1", "tradeoff_pair_2", "tradeoff_pair_3",
        "tradeoff_pair_4", "tradeoff_pair_5",
        "overall_satisfaction", "usage_intent", "vs_self_scheduling",
        "nps_score", "conflict_clarity_score",
        "reported_issues_json", "best_aspect", "needs_improvement",
    ]
    updatable = [c for c in columns if c not in ("user_id", "schedule_id")]

    with db_transaction() as cur:
        cur.execute("SELECT id FROM schedules WHERE id=%s AND user_id=%s", (schedule_id, user_id))
        if not cur.fetchone():
            raise NotFoundError()
        cur.execute("SELECT id FROM schedule_histories WHERE schedule_id=%s AND user_id=%s "
                    "ORDER BY version DESC LIMIT 1", (schedule_id, user_id))
        history = cur.fetchone()

        values = [
            user_id, schedule_id, history["id"] if history else None, sys_metrics_json,
            crit_vals["sat_coverage"], crit_vals["imp_coverage"],
            crit_vals["sat_priority"], crit_vals["imp_priority"],
            crit_vals["sat_deadline"], crit_vals["imp_deadline"],
            crit_vals["sat_continuity"], crit_vals["imp_continuity"],
            crit_vals["sat_balance"], crit_vals["imp_balance"],
            crit_vals["sat_constraints"], crit_vals["imp_constraints"],
            crit_vals["sat_feasibility"], crit_vals["imp_feasibility"],
            *tradeoff_vals,
            overall, usage, vs_self, nps, conflict_clarity,
            json.dumps(issues, ensure_ascii=False), best_aspect, needs_improvement,
        ]
        placeholders = ", ".join(["%s"] * len(columns))
        updates = ", ".join(f"{col}=VALUES({col})" for col in updatable)
        cur.execute(
            f"INSERT INTO feedbacks ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON DUPLICATE KEY UPDATE {updates}",
            values,
        )
        cur.execute("SELECT id FROM feedbacks WHERE user_id=%s AND schedule_id=%s",
                    (user_id, schedule_id))
        return cur.fetchone()["id"]


def get_feedback(user_id: int, schedule_id: int) -> dict | None:
    with db_readonly() as cur:
        cur.execute("SELECT * FROM feedbacks WHERE user_id=%s AND schedule_id=%s",
                    (int(user_id), int(schedule_id)))
        row = cur.fetchone()
    if not row:
        return None
    return {
        "feedback_id": row["id"],
        "schedule_id": row["schedule_id"],
        "history_id": row["history_id"],
        "system_metrics": json.loads(row["system_metrics_json"]) if row["system_metrics_json"] else None,
        "criteria": {
            key: {"satisfaction": row[f"sat_{key}"], "importance": row[f"imp_{key}"]}
            for key in CRITERIA_KEYS
        },
        "weighted_satisfaction": _weighted_satisfaction(row),
        "tradeoffs": [row[f"tradeoff_pair_{i}"] for i in range(1, 6)],
        "overall_satisfaction": row["overall_satisfaction"],
        "usage_intent": row["usage_intent"],
        "vs_self_scheduling": row["vs_self_scheduling"],
        "nps_score": row["nps_score"],
        "conflict_clarity_score": row["conflict_clarity_score"],
        "reported_issues": json.loads(row["reported_issues_json"] or "[]"),
        "best_aspect": row["best_aspect"],
        "needs_improvement": row["needs_improvement"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


def _require_admin(admin_password: str) -> None:
    expected = get_backend_settings().admin_password
    if not hmac.compare_digest((admin_password or "").encode("utf-8"), expected.encode("utf-8")):
        raise AuthError("Sai mật khẩu quản trị.")


def export_all_feedbacks_csv(admin_password: str) -> bytes:
    """Xuất CSV UTF-8 BOM toàn bộ câu trả lời khảo sát kèm điểm hài lòng trọng số cho Excel/SPSS/Python."""
    _require_admin(admin_password)
    with db_readonly() as cur:
        cur.execute(REPORT_SQL)
        rows = cur.fetchall()

    columns = [
        "feedback_id", "created_at", "updated_at", "username", "role_group",
        "schedule_id", "week_start", "schedule_version", "creation_source",
        "applied_option_id", "status", "proven_optimal",
        "total_tasks", "scheduled_tasks", "unscheduled_tasks",
        "sat_coverage", "imp_coverage",
        "sat_priority", "imp_priority",
        "sat_deadline", "imp_deadline",
        "sat_continuity", "imp_continuity",
        "sat_balance", "imp_balance",
        "sat_constraints", "imp_constraints",
        "sat_feasibility", "imp_feasibility",
        "weighted_satisfaction",
        "tradeoff_pair_1", "tradeoff_pair_2", "tradeoff_pair_3",
        "tradeoff_pair_4", "tradeoff_pair_5",
        "overall_satisfaction", "usage_intent", "vs_self_scheduling",
        "nps_score", "conflict_clarity_score",
        "reported_issues", "best_aspect", "needs_improvement",
        "system_metrics_json",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        issues_list = json.loads(row["reported_issues_json"] or "[]")
        out = {col: row.get(col) for col in columns}
        out["weighted_satisfaction"] = _weighted_satisfaction(row)
        out["reported_issues"] = ";".join(issues_list)
        writer.writerow({k: ("" if v is None else v) for k, v in out.items()})
    return buffer.getvalue().encode("utf-8-sig")


def get_summary_stats(admin_password: str) -> dict:
    """Thống kê tổng hợp toàn diện (NPS, điểm từng tiêu chí, xu hướng đánh đổi, tỉ lệ vấn đề) cho báo cáo."""
    _require_admin(admin_password)
    with db_readonly() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM users")
        users = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM schedules WHERE creation_source='cp_sat'")
        first_runs = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM schedules WHERE creation_source='cp_sat' AND status='NOT_FOUND'")
        conflicts = cur.fetchone()["n"]
        cur.execute("SELECT option_code, COUNT(*) AS n FROM conflict_options WHERE is_selected=1 GROUP BY option_code")
        option_choices = {str(r["option_code"]): r["n"] for r in cur.fetchall()}
        cur.execute("SELECT * FROM feedbacks")
        fb_rows = cur.fetchall()

    total_fb = len(fb_rows)
    criteria_avg = {}
    for key in CRITERIA_KEYS:
        sats = [r[f"sat_{key}"] for r in fb_rows if r[f"sat_{key}"] is not None]
        imps = [r[f"imp_{key}"] for r in fb_rows if r[f"imp_{key}"] is not None]
        criteria_avg[key] = {
            "avg_satisfaction": round(sum(sats) / len(sats), 2) if sats else None,
            "avg_importance": round(sum(imps) / len(imps), 2) if imps else None,
            "na_count": total_fb - len(sats),
        }

    tradeoff_avg = {
        f"pair_{i}": (round(sum(r[f"tradeoff_pair_{i}"] for r in fb_rows) / total_fb, 2) if total_fb else None)
        for i in range(1, 6)
    }

    promoters = sum(1 for r in fb_rows if r["nps_score"] >= 9)
    detractors = sum(1 for r in fb_rows if r["nps_score"] <= 6)
    nps = round(100 * (promoters - detractors) / total_fb, 1) if total_fb else None

    issue_counts: dict[str, int] = {}
    usage_counts: dict[str, int] = {}
    vs_self_counts: dict[str, int] = {}
    for r in fb_rows:
        usage_counts[r["usage_intent"]] = usage_counts.get(r["usage_intent"], 0) + 1
        vs_self_counts[r["vs_self_scheduling"]] = vs_self_counts.get(r["vs_self_scheduling"], 0) + 1
        for tag in json.loads(r["reported_issues_json"] or "[]"):
            issue_counts[tag] = issue_counts.get(tag, 0) + 1

    return {
        "users": users,
        "first_runs": first_runs,
        "conflict_runs": conflicts,
        "pct_conflict": round(100 * conflicts / first_runs, 1) if first_runs else 0.0,
        "option_choices": option_choices,
        "total_feedbacks": total_fb,
        "avg_overall_satisfaction": (
            round(sum(r["overall_satisfaction"] for r in fb_rows) / total_fb, 2) if total_fb else None
        ),
        "nps": nps,
        "criteria_summary": criteria_avg,
        "tradeoff_averages": tradeoff_avg,
        "usage_intent_counts": usage_counts,
        "vs_self_counts": vs_self_counts,
        "issue_tag_counts": issue_counts,
    }
