"""Trang quản trị: số liệu tổng quát về người dùng và đánh giá lịch."""
from __future__ import annotations

import csv
import io
from collections import Counter
from datetime import datetime, timedelta, timezone

import altair as alt
import streamlit as st

from . import repository
from .auth import change_admin_password
from .metrics import _hm, _pct
from .rating_schema import CRITERIA, TRADEOFFS
from .ui_auth import logout

VN = timezone(timedelta(hours=7))


def _local(iso: str | None) -> str:
    if not iso:
        return "—"
    return datetime.fromisoformat(iso).astimezone(VN).strftime("%d/%m/%Y %H:%M")


def _csv(rows: list[dict]) -> bytes:
    if not rows:
        return b""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return ("﻿" + out.getvalue()).encode("utf-8")  # BOM để Excel đọc đúng tiếng Việt


def _ratings_rows(ratings) -> list[dict]:
    rows = []
    for r in ratings:
        row = {
            "Người dùng": r["username"], "Họ tên": r["full_name"], "Nhóm": r["user_group"],
            "Tuần": r["week_start"], "Cập nhật": _local(r["updated_at"]),
            "Hài lòng chung": r["overall"], "Giới thiệu (0-10)": r["nps"], "Cách dùng": r["adoption"],
            "So với tự xếp": r["vs_manual"], "Độ dễ hiểu phương án": r["conflict_clarity"],
        }
        for item in CRITERIA:
            c = r["criteria"].get(item["key"], {})
            row[f"{item['short']} – hài lòng"] = c.get("satisfaction")
            row[f"{item['short']} – quan trọng"] = c.get("importance")
        for item in TRADEOFFS:
            row[f"Đánh đổi {item['key']}"] = r["tradeoffs"].get(item["key"])
        row["Vấn đề"] = "; ".join(r["problems"])
        row["Điều tốt"] = r["comment_good"]
        row["Cần cải thiện"] = r["comment_improve"]
        for name, value in r["metrics"].items():
            row[f"metric_{name}"] = value
        rows.append(row)
    return rows


def _kpis(data) -> None:
    k = data["kpi"]
    a, b, c, d = st.columns(4)
    a.metric("Tổng số người dùng", k["users_total"], f"+{k['users_new_7d']} trong 7 ngày")
    b.metric("Hoạt động 7 ngày qua", k["users_active_7d"])
    c.metric("Lượt đăng nhập (30 ngày)", k["logins_30d"])
    d.metric("Lịch đã chốt", k["finalized_total"],
             f"{k['finalized_with_conflict']} lịch qua xử lý xung đột", delta_color="off")
    e, f, g, h = st.columns(4)
    e.metric("Lượt đánh giá", k["ratings_total"], f"{k['raters']} người")
    f.metric("Tỷ lệ phản hồi", _pct(k["response_rate"]), help="Số đánh giá / số lịch đã chốt")
    g.metric("Hài lòng chung (TB)", f"{k['overall_mean']} / 5" if k["overall_mean"] else "—",
             f"độ lệch chuẩn {k['overall_std']}" if k["overall_mean"] else None, delta_color="off")
    h.metric("NPS", k["nps"] if k["nps"] is not None else "—",
             help="% người chấm 9–10 trừ % người chấm 0–6, trong khoảng −100 đến 100.")
    st.caption(f"Tỷ lệ chấp nhận lịch (dùng nguyên hoặc chỉnh nhỏ): **{_pct(k['accept_rate'])}** · "
               f"Lịch xếp đủ mọi việc: **{k['finalized_complete']}/{k['finalized_total']}**")


def _criteria_table(data) -> None:
    st.markdown("##### Bảng tổng hợp đánh giá theo tiêu chí (trục Pareto)")
    rows = [{
        "Tiêu chí": c["title"], "Số lượt": c["n"],
        "Hài lòng TB (1–5)": c["satisfaction"], "Quan trọng TB (1–5)": c["importance"],
        "Độ lệch chuẩn": c["std"],
        "Tỷ lệ không hài lòng (≤2)": c["low_share"], "Khoảng cách ưu tiên": c["priority_gap"],
    } for c in data["criteria"]]
    st.dataframe(rows, hide_index=True, use_container_width=True, column_config={
        "Hài lòng TB (1–5)": st.column_config.ProgressColumn(min_value=0, max_value=5, format="%.2f"),
        "Quan trọng TB (1–5)": st.column_config.ProgressColumn(min_value=0, max_value=5, format="%.2f"),
        "Tỷ lệ không hài lòng (≤2)": st.column_config.NumberColumn(format="percent"),
    })
    st.caption("Khoảng cách ưu tiên = trung bình (mức quan trọng × (5 − mức hài lòng)). Càng cao thì càng cần cải thiện.")
    ranked = [c for c in data["criteria"] if c["priority_gap"] is not None]
    if ranked:
        worst = sorted(ranked, key=lambda c: -c["priority_gap"])[:2]
        st.info("Nên ưu tiên cải thiện: " + "; ".join(f"**{c['title']}** (khoảng cách {c['priority_gap']})" for c in worst))


def _matrix(data) -> None:
    points = [c for c in data["criteria"] if c["satisfaction"] is not None and c["importance"] is not None]
    if not points:
        return
    st.markdown("##### Ma trận mức quan trọng – mức hài lòng")
    frame = alt.Data(values=[{"Tiêu chí": c["short"], "Quan trọng": c["importance"], "Hài lòng": c["satisfaction"]}
                             for c in points])
    base = alt.Chart(frame).encode(
        x=alt.X("Quan trọng:Q", scale=alt.Scale(domain=[0.5, 5.5]), title="Mức quan trọng trung bình"),
        y=alt.Y("Hài lòng:Q", scale=alt.Scale(domain=[0.5, 5.5]), title="Mức hài lòng trung bình"))
    dots = base.mark_circle(size=170, color="#2f78ba")
    labels = base.mark_text(dy=-14, fontSize=12).encode(text="Tiêu chí:N")
    guide = alt.Chart(alt.Data(values=[{"v": 3}]))
    lines = (guide.mark_rule(strokeDash=[4, 4], color="#9aa7b8").encode(x=alt.X("v:Q"))
             + guide.mark_rule(strokeDash=[4, 4], color="#9aa7b8").encode(y=alt.Y("v:Q")))
    st.altair_chart((lines + dots + labels).properties(height=320), use_container_width=True)
    st.caption("Góc dưới bên phải (quan trọng cao, hài lòng thấp) là nhóm tiêu chí cần cải thiện trước.")


def _tradeoffs(data) -> None:
    st.markdown("##### Người dùng sẵn sàng đánh đổi điều gì?")
    rows = [{
        "Bên A": t["a"], "Bên B": t["b"], "Nghiêng A": t["toward_a"], "Cân bằng": t["balanced"],
        "Nghiêng B": t["toward_b"], "Xu hướng (−2 = A, +2 = B)": t["mean"],
    } for t in data["tradeoffs"]]
    st.dataframe(rows, hide_index=True, use_container_width=True)


def _trend(data) -> None:
    today = datetime.now(VN).date()
    days = [(today - timedelta(days=i)) for i in range(29, -1, -1)]
    def count(values):
        counter = Counter(datetime.fromisoformat(v).astimezone(VN).date() for v in values)
        return [counter.get(day, 0) for day in days]
    st.markdown("##### 30 ngày gần nhất")
    labels = [f"{d:%d/%m}" for d in days]
    frame = {
        "Ngày": labels * 3,
        "Loại": ["Đăng ký mới"] * 30 + ["Lịch đã chốt"] * 30 + ["Đánh giá"] * 30,
        "Số lượng": count(u["created_at"] for u in data["users"]) + count(f["at"] for f in data["finalized"])
        + count(r["created_at"] for r in data["ratings"]),
    }
    chart = alt.Chart(alt.Data(values=[dict(zip(frame, row)) for row in zip(*frame.values())])).mark_line(
        point=True).encode(x=alt.X("Ngày:N", sort=labels, axis=alt.Axis(labelAngle=-45)), y="Số lượng:Q", color="Loại:N")
    st.altair_chart(chart.properties(height=260), use_container_width=True)


def _overview(data) -> None:
    _kpis(data)
    st.divider()
    left, right = st.columns([3, 2])
    with left:
        _criteria_table(data)
    with right:
        _matrix(data)
    st.divider()
    a, b, c = st.columns(3)
    with a:
        st.markdown("##### Phân bố mức hài lòng chung")
        dist = data["overall_distribution"]
        st.bar_chart({"Số lượt": {f"{s} sao": n for s, n in dist.items()}}, height=230)
    with b:
        st.markdown("##### Cách người dùng dùng lịch")
        adoption = data["adoption"]
        if adoption:
            st.bar_chart({"Số lượt": adoption}, horizontal=True, height=230)
        else:
            st.caption("Chưa có dữ liệu.")
    with c:
        st.markdown("##### Vấn đề được nêu nhiều nhất")
        if data["problems"]:
            st.bar_chart({"Số lượt": data["problems"]}, horizontal=True, height=230)
        else:
            st.caption("Chưa có dữ liệu.")
    st.divider()
    _tradeoffs(data)
    st.markdown("##### Chỉ số khách quan trung bình của các lịch được đánh giá")
    m = data["metric_means"]
    p, q, r, s, t = st.columns(5)
    p.metric("Việc xếp đủ", _pct(m["coverage_task_ratio"]))
    q.metric("Điểm ưu tiên đạt", _pct(m["priority_weighted_ratio"]))
    r.metric("Độ dài phiên TB", _hm(m["avg_chunk_min"]) if m["avg_chunk_min"] else "—")
    s.metric("Ngày nặng nhất TB", _hm(m["max_day_minutes"]) if m["max_day_minutes"] else "—")
    t.metric("Mức lấp đầy giờ rảnh", _pct(m["utilization_ratio"]))
    st.divider()
    _trend(data)


def _ratings_tab(data) -> None:
    ratings = data["ratings"]
    if not ratings:
        st.info("Chưa có đánh giá nào.")
        return
    a, b = st.columns(2)
    scores = a.multiselect("Lọc theo mức hài lòng chung", [1, 2, 3, 4, 5], default=[1, 2, 3, 4, 5])
    groups = sorted({r["user_group"] or "—" for r in ratings})
    picked = b.multiselect("Lọc theo nhóm người dùng", groups, default=groups)
    shown = [r for r in ratings if r["overall"] in scores and (r["user_group"] or "—") in picked]
    st.caption(f"{len(shown)}/{len(ratings)} đánh giá")
    st.dataframe([{
        "Người dùng": r["username"], "Nhóm": r["user_group"], "Tuần": r["week_start"],
        "Cập nhật": _local(r["updated_at"]), "Hài lòng": r["overall"], "NPS": r["nps"],
        "Cách dùng": r["adoption"], "Vấn đề": "; ".join(r["problems"]),
        "Điều tốt": r["comment_good"], "Cần cải thiện": r["comment_improve"],
    } for r in shown], hide_index=True, use_container_width=True)
    st.download_button("Tải toàn bộ đánh giá (CSV)", _csv(_ratings_rows(shown)),
                       "ratings.csv", mime="text/csv")


def _users_tab(data) -> None:
    users = data["users"]
    rated = Counter(r["user_id"] for r in data["ratings"])
    rows = [{
        "Tên đăng nhập": u["username"], "Họ tên": u["full_name"], "Nhóm": u["user_group"],
        "Email": u["email"] or "", "Ngày đăng ký": _local(u["created_at"]),
        "Đăng nhập gần nhất": _local(u["last_login_at"]), "Số lần đăng nhập": u["login_count"],
        "Số đánh giá": rated.get(u["id"], 0),
    } for u in users]
    if not rows:
        st.info("Chưa có người dùng nào đăng ký.")
        return
    groups = Counter(u["user_group"] or "—" for u in users)
    st.markdown("##### Cơ cấu nhóm người dùng")
    st.bar_chart({"Số người": dict(groups)}, horizontal=True, height=200)
    st.dataframe(rows, hide_index=True, use_container_width=True)
    st.download_button("Tải danh sách người dùng (CSV)", _csv(rows), "users.csv", mime="text/csv")


def _settings_tab() -> None:
    st.markdown("##### Đổi mật khẩu quản trị viên")
    st.caption("Mật khẩu mặc định là 123. Nên đổi trước khi đưa ứng dụng cho người khác dùng.")
    with st.form("admin_password_form"):
        current = st.text_input("Mật khẩu hiện tại", type="password")
        new = st.text_input("Mật khẩu mới", type="password")
        confirm = st.text_input("Nhập lại mật khẩu mới", type="password")
        if st.form_submit_button("Đổi mật khẩu", type="primary"):
            error = change_admin_password(current, new, confirm)
            if error:
                st.error(error)
            else:
                st.success("Đã đổi mật khẩu.")


def render_admin_page(user) -> None:
    head, action = st.columns([5, 1], vertical_alignment="center")
    head.html('<div class="app-banner"><div><strong>Bảng điều khiển quản trị</strong>'
              '<span>Smart Weekly Scheduling · tổng quan người dùng và đánh giá lịch</span></div></div>')
    if action.button("Đăng xuất", key="admin_logout", use_container_width=True):
        logout()
    data = repository.overview()
    overview, ratings, users, settings = st.tabs(["Tổng quan", "Đánh giá chi tiết", "Người dùng", "Cài đặt"])
    with overview:
        _overview(data)
    with ratings:
        _ratings_tab(data)
    with users:
        _users_tab(data)
    with settings:
        _settings_tab()
