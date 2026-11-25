"""Bảng đánh giá lịch hiện ra sau khi người dùng chốt lịch cuối cùng."""
from __future__ import annotations

import json
from html import escape

import streamlit as st

from . import repository
from .metrics import _hm, _pct, compute_schedule_metrics, criterion_facts, schedule_key
from .rating_schema import (
    ADOPTION_OPTIONS, CRITERIA, IMPORTANCE_LABELS, NO_BASELINE, NOT_APPLICABLE, PROBLEMS,
    SATISFACTION_LABELS, TRADEOFF_LABELS, TRADEOFFS, VS_MANUAL_LABELS,
)

CSS = """
<style>
.st-key-rating_card{padding:6px 12px}
.st-key-auth_card,.st-key-rating_card{background:var(--app-surface)!important;border:1px solid var(--app-border)!important;border-radius:16px!important}
.st-key-auth_card [data-testid="stFormSubmitButton"] button,.st-key-rating_card [data-testid="stFormSubmitButton"] button{background:var(--app-blue)!important;color:#fff!important;border-color:var(--app-blue)!important}
.st-key-auth_card [data-testid="stFormSubmitButton"] button p,.st-key-rating_card [data-testid="stFormSubmitButton"] button p{color:#fff!important}
.rt-scale{font-size:13px;color:var(--app-muted);margin:0 0 8px}
.rt-fact{font-size:13px;color:var(--app-muted);margin:2px 0}
.rt-fact b{color:var(--app-text)}
.rt-title{font-weight:700;font-size:16px;color:var(--app-text);margin:0}
.rt-q{font-size:14px;color:var(--app-muted);margin:2px 0 6px}
.rt-tag{display:inline-block;font-size:11px;font-weight:600;border-radius:10px;padding:2px 8px;background:var(--app-soft);color:var(--app-blue);margin-left:8px}
.rt-ab{border:1px solid var(--app-border);border-radius:10px;padding:10px 12px;font-size:14px;height:100%;background:var(--app-soft);color:var(--app-text)}
.rt-ab b{color:var(--app-blue)}
</style>
"""

SAT_CHOICES = ["1", "2", "3", "4", "5", NOT_APPLICABLE]
IMP_CHOICES = ["1", "2", "3", "4", "5"]
LEVEL_HELP_SAT = " · ".join(SATISFACTION_LABELS.values())
LEVEL_HELP_IMP = " · ".join(IMPORTANCE_LABELS.values())


# ---------------------------------------------------------------- chốt lịch
def finalize_schedule(user, context, result, week_start, applied_options) -> None:
    """Gọi khi người dùng chốt lịch (nút Chốt lịch hoặc tải lịch xuống)."""
    metrics = compute_schedule_metrics(context, result, applied_options)
    key = schedule_key(context, result, week_start)
    repository.record_finalized(user.id, key, week_start, metrics["complete"], metrics["options_applied"] > 0)
    st.session_state.rating_open_key = key
    st.session_state.pop("rating_submitted_key", None)


def render_finalize_and_rating(user, context, result, week_start, applied_options) -> None:
    metrics = compute_schedule_metrics(context, result, applied_options)
    key = schedule_key(context, result, week_start)
    st.html(CSS)
    with st.container(border=True, key="rating_card"):
        st.subheader("Chốt lịch cuối cùng")
        if st.session_state.get("rating_open_key") != key:
            st.caption("Khi bạn đã hài lòng với lịch đang hiển thị, hãy chốt lịch để chuyển sang bước đánh giá. "
                       "Bạn cũng có thể tải lịch xuống, bảng đánh giá sẽ tự mở.")
            if not metrics["complete"]:
                st.warning(f"Lịch này vẫn còn {metrics['tasks_unplaced']} việc chưa xếp được; "
                           "kết quả đánh giá sẽ ghi nhận điều đó.")
            st.button("✅ Chốt lịch này và đánh giá", type="primary", key=f"finalize_{key}",
                      on_click=finalize_schedule, args=(user, context, result, week_start, applied_options))
            return
        _render_form(user, key, week_start, metrics)


# ------------------------------------------------------------------ biểu mẫu
def _index(options, value):
    return options.index(value) if value in options else None


def _radio(label, options, key, existing=None, help=None, horizontal=True):
    return st.radio(label, options, index=_index(options, existing), horizontal=horizontal,
                    key=key, help=help)


def _num(choice):
    return None if choice in (None, NOT_APPLICABLE) else int(choice)


def _render_form(user, key, week_start, metrics) -> None:
    existing = repository.get_rating(user.id, key)
    prior = json.loads(existing["criteria_json"]) if existing else {}
    prior_trade = json.loads(existing["tradeoffs_json"]) if existing else {}
    prior_problems = json.loads(existing["problems_json"]) if existing else []
    facts = criterion_facts(metrics)
    submitted_key = st.session_state.get("rating_submitted_key")

    if submitted_key == key:
        _render_thanks(user, key)
        return

    st.subheader("Đánh giá lịch vừa chốt")
    st.caption("Mất khoảng 3–4 phút. Hãy chấm theo cảm nhận của bạn; phần “Hệ thống đo được” chỉ để tham khảo, "
               "bạn không bắt buộc phải đồng ý với nó. Mọi câu đều cần trả lời, riêng mức hài lòng có thể chọn “Không áp dụng”.")
    if existing:
        st.info("Bạn đã đánh giá lịch này trước đó. Gửi lại sẽ cập nhật đánh giá cũ.")

    cols = st.columns(4)
    cols[0].metric("Việc xếp đủ", f"{metrics['tasks_fully_placed']}/{metrics['tasks_total']}")
    cols[1].metric("Đúng hạn", _pct(metrics["on_time_ratio"]))
    cols[2].metric("Số phiên làm việc", metrics["chunks_total"])
    cols[3].metric("Ngày nặng nhất", _hm(metrics["max_day_minutes"]))

    with st.form(f"rating_form_{key}", border=False):
        # ---- Phần A -------------------------------------------------
        st.markdown("#### A. Chấm điểm theo từng tiêu chí")
        st.html('<div class="rt-scale"><b>Mức hài lòng</b>: 1 = rất không hài lòng · 3 = trung lập · 5 = rất hài lòng. '
                '<b>Mức quan trọng</b>: 1 = không quan trọng · 5 = rất quan trọng với riêng bạn.</div>')
        answers_criteria = {}
        for item in CRITERIA:
            old = prior.get(item["key"], {})
            with st.container(border=True):
                st.html(f'<p class="rt-title">{escape(item["title"])}<span class="rt-tag">{escape(item["short"])}</span></p>'
                        f'<p class="rt-q">{escape(item["question"])}</p>'
                        + "".join(f'<p class="rt-fact"><b>Hệ thống đo được:</b> {escape(line)}</p>'
                                  for line in facts[item["key"]][:1])
                        + "".join(f'<p class="rt-fact">{escape(line)}</p>' for line in facts[item["key"]][1:]))
                left, right = st.columns(2)
                old_sat = old.get("satisfaction") if item["key"] in prior else None
                old_sat_label = (NOT_APPLICABLE if (item["key"] in prior and old_sat is None)
                                 else (str(old_sat) if old_sat else None))
                with left:
                    sat = _radio("Mức hài lòng của bạn", SAT_CHOICES, f"rt_{key}_{item['key']}_sat",
                                 old_sat_label, help=LEVEL_HELP_SAT)
                with right:
                    imp = _radio("Tiêu chí này quan trọng với bạn", IMP_CHOICES, f"rt_{key}_{item['key']}_imp",
                                 str(old["importance"]) if old.get("importance") else None, help=LEVEL_HELP_IMP)
                answers_criteria[item["key"]] = (sat, imp)

        # ---- Phần B -------------------------------------------------
        st.markdown("#### B. Khi buộc phải đánh đổi, bạn nghiêng về bên nào?")
        st.caption("Không thể có lịch hoàn hảo ở mọi mặt. Với mỗi cặp, hãy chọn điều bạn sẵn sàng ưu tiên.")
        answers_trade = {}
        labels = list(TRADEOFF_LABELS.values())
        for number, item in enumerate(TRADEOFFS, 1):
            with st.container(border=True):
                a_col, b_col = st.columns(2)
                a_col.html(f'<div class="rt-ab"><b>A.</b> {escape(item["a"])}</div>')
                b_col.html(f'<div class="rt-ab"><b>B.</b> {escape(item["b"])}</div>')
                old_value = prior_trade.get(item["key"])
                answers_trade[item["key"]] = _radio(
                    f"Cặp {number}", labels, f"rt_{key}_trade_{item['key']}",
                    TRADEOFF_LABELS.get(old_value) if old_value is not None else None)

        # ---- Phần C -------------------------------------------------
        st.markdown("#### C. Đánh giá chung")
        overall_labels = list(SATISFACTION_LABELS.values())
        overall = _radio("Nhìn tổng thể, bạn hài lòng với lịch này ở mức nào?", overall_labels,
                         f"rt_{key}_overall",
                         SATISFACTION_LABELS.get(existing["overall"]) if existing else None, horizontal=False)
        adoption = _radio("Bạn sẽ dùng lịch này như thế nào?", ADOPTION_OPTIONS, f"rt_{key}_adoption",
                          existing["adoption"] if existing else None, horizontal=False)
        manual_options = list(VS_MANUAL_LABELS.values()) + [NO_BASELINE]
        vs_old = None
        if existing:
            vs_old = VS_MANUAL_LABELS.get(existing["vs_manual"]) if existing["vs_manual"] else NO_BASELINE
        vs_manual = _radio("So với cách bạn tự xếp lịch thường ngày, lịch này…", manual_options,
                           f"rt_{key}_vs_manual", vs_old, horizontal=False)
        nps = _radio("Khả năng bạn giới thiệu công cụ này cho người khác (0 = không bao giờ, 10 = chắc chắn)",
                     [str(n) for n in range(11)], f"rt_{key}_nps",
                     str(existing["nps"]) if existing and existing["nps"] is not None else None)
        clarity = None
        if metrics["options_applied"] > 0:
            clarity = _radio("Các phương án xử lý xung đột (bỏ việc / giảm thời lượng / nới ràng buộc) dễ hiểu và dễ chọn?",
                             list(SATISFACTION_LABELS.values()), f"rt_{key}_clarity",
                             SATISFACTION_LABELS.get(existing["conflict_clarity"]) if existing else None)

        # ---- Phần D -------------------------------------------------
        st.markdown("#### D. Vấn đề và góp ý")
        problems = st.pills("Lịch này có vấn đề nào sau đây? (chọn tất cả phù hợp)", PROBLEMS,
                            selection_mode="multi", default=[p for p in prior_problems if p in PROBLEMS],
                            key=f"rt_{key}_problems")
        good = st.text_area("Điều làm bạn hài lòng nhất (không bắt buộc)", max_chars=600, height=80,
                            value=(existing["comment_good"] or "") if existing else "", key=f"rt_{key}_good")
        improve = st.text_area("Điều cần cải thiện nhất (không bắt buộc)", max_chars=600, height=80,
                               value=(existing["comment_improve"] or "") if existing else "", key=f"rt_{key}_improve")
        submit = st.form_submit_button("Gửi đánh giá", type="primary", use_container_width=True)

    if not submit:
        return

    missing = [item["title"] for item in CRITERIA
               if answers_criteria[item["key"]][0] is None or answers_criteria[item["key"]][1] is None]
    missing += [f"Cặp đánh đổi {n}" for n, item in enumerate(TRADEOFFS, 1) if answers_trade[item["key"]] is None]
    for label, value in (("Mức hài lòng chung", overall), ("Cách dùng lịch", adoption),
                         ("So với tự xếp lịch", vs_manual), ("Khả năng giới thiệu", nps)):
        if value is None:
            missing.append(label)
    if metrics["options_applied"] > 0 and clarity is None:
        missing.append("Độ dễ hiểu của các phương án xử lý xung đột")
    if missing:
        st.error("Bạn chưa trả lời: " + "; ".join(missing) + ".")
        return

    reverse_trade = {v: k for k, v in TRADEOFF_LABELS.items()}
    reverse_sat = {v: k for k, v in SATISFACTION_LABELS.items()}
    reverse_manual = {v: k for k, v in VS_MANUAL_LABELS.items()}
    payload = {
        "criteria": {k: {"satisfaction": _num(sat), "importance": int(imp)}
                     for k, (sat, imp) in answers_criteria.items()},
        "tradeoffs": {k: reverse_trade[v] for k, v in answers_trade.items()},
        "overall": reverse_sat[overall],
        "adoption": adoption,
        "vs_manual": reverse_manual.get(vs_manual),
        "nps": int(nps),
        "conflict_clarity": reverse_sat.get(clarity) if clarity else None,
        "problems": list(problems or []),
        "comment_good": good,
        "comment_improve": improve,
    }
    repository.save_rating(user.id, key, week_start, payload, metrics)
    st.session_state.rating_submitted_key = key
    st.rerun()


def _render_thanks(user, key) -> None:
    rating = repository.get_rating(user.id, key)
    st.success("Cảm ơn bạn! Đánh giá đã được ghi nhận.")
    if rating:
        criteria = json.loads(rating["criteria_json"])
        pairs = [(v["satisfaction"], v["importance"]) for v in criteria.values() if v["satisfaction"] is not None]
        if pairs:
            weight = sum(i for _, i in pairs)
            score = sum(s * i for s, i in pairs) / weight
            st.metric("Điểm hài lòng có trọng số theo ưu tiên của bạn", f"{score:.1f} / 5",
                      help="Trung bình mức hài lòng, mỗi tiêu chí nhân với mức quan trọng bạn đã chọn.")
        rows = [{"Tiêu chí": item["title"],
                 "Hài lòng": criteria[item["key"]]["satisfaction"] or "—",
                 "Quan trọng": criteria[item["key"]]["importance"]} for item in CRITERIA]
        st.dataframe(rows, hide_index=True, use_container_width=True)
    if st.button("Sửa lại đánh giá", key=f"edit_rating_{key}"):
        st.session_state.pop("rating_submitted_key", None)
        st.rerun()
