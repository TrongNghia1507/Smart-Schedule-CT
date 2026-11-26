"""Trang đăng ký / đăng nhập (người dùng và quản trị viên)."""
from __future__ import annotations

import streamlit as st

from .auth import ADMIN_USERNAME, MIN_PASSWORD_LEN, USER_GROUPS, login_admin, login_user, register_user

KEEP_ON_LOGIN = ("ui_theme", "ui_language")

CSS = """
<style>
.auth-hero{background:var(--app-header);color:#fff;border-radius:16px;padding:26px 30px;margin:0 0 18px}
.auth-hero strong{font-size:26px;letter-spacing:-.4px;display:block}
.auth-hero span{color:#c7dded;font-size:15px;display:block;margin-top:6px}
.st-key-auth_card{padding:6px 10px}
.st-key-auth_card,.st-key-rating_card{background:var(--app-surface)!important;border:1px solid var(--app-border)!important;border-radius:16px!important}
.st-key-auth_card [data-testid="stFormSubmitButton"] button,.st-key-rating_card [data-testid="stFormSubmitButton"] button{background:var(--app-blue)!important;color:#fff!important;border-color:var(--app-blue)!important}
.st-key-auth_card [data-testid="stFormSubmitButton"] button p,.st-key-rating_card [data-testid="stFormSubmitButton"] button p{color:#fff!important}
.auth-note{font-size:13px;color:var(--app-muted);margin-top:4px}
</style>
"""


def start_session(user) -> None:
    """Đặt người dùng hiện tại và bỏ toàn bộ trạng thái của phiên trước."""
    keep = {k: st.session_state[k] for k in KEEP_ON_LOGIN if k in st.session_state}
    st.session_state.clear()
    st.session_state.update(keep)
    st.session_state.app_version = 4  # khớp app.py để không bị xoá trạng thái lần nữa
    st.session_state.auth_user = user
    st.rerun()


def logout() -> None:
    keep = {k: st.session_state[k] for k in KEEP_ON_LOGIN if k in st.session_state}
    st.session_state.clear()
    st.session_state.update(keep)
    st.rerun()


def _login_tab() -> None:
    role = st.segmented_control("Đăng nhập với tư cách", ["Người dùng", "Quản trị viên"],
                                default="Người dùng", key="login_role", required=True)
    with st.form("login_form"):
        if role == "Quản trị viên":
            st.text_input("Tài khoản", value=ADMIN_USERNAME, disabled=True)
            password = st.text_input("Mật khẩu", type="password", key="admin_password")
            username = ADMIN_USERNAME
        else:
            username = st.text_input("Tên đăng nhập", key="login_username", max_chars=30)
            password = st.text_input("Mật khẩu", type="password", key="login_password")
        submitted = st.form_submit_button("Đăng nhập", type="primary", use_container_width=True)
    if not submitted:
        return
    if role != "Quản trị viên" and not username.strip():
        st.error("Hãy nhập tên đăng nhập.")
        return
    user, error = login_admin(password) if role == "Quản trị viên" else login_user(username, password)
    if error:
        st.error(error)
        return
    start_session(user)


def _register_tab() -> None:
    st.caption("Dành cho người chưa có tài khoản. Dữ liệu lịch của mỗi người được lưu riêng.")
    with st.form("register_form"):
        full_name = st.text_input("Họ và tên *", key="reg_full_name", max_chars=80)
        a, b = st.columns(2)
        username = a.text_input("Tên đăng nhập *", key="reg_username", max_chars=30,
                                help="3–30 ký tự: chữ thường không dấu, số, dấu chấm hoặc gạch dưới.")
        group = b.selectbox("Bạn thuộc nhóm nào?", USER_GROUPS, key="reg_group")
        email = st.text_input("Email (không bắt buộc)", key="reg_email", max_chars=120)
        c, d = st.columns(2)
        password = c.text_input(f"Mật khẩu * (≥ {MIN_PASSWORD_LEN} ký tự)", type="password", key="reg_password")
        confirm = d.text_input("Nhập lại mật khẩu *", type="password", key="reg_confirm")
        consent = st.checkbox("Tôi đồng ý để hệ thống lưu các đánh giá và chỉ số lịch của tôi nhằm cải thiện thuật toán xếp lịch.",
                              key="reg_consent")
        submitted = st.form_submit_button("Tạo tài khoản", type="primary", use_container_width=True)
    if not submitted:
        return
    user, errors = register_user(username, full_name, email, group, password, confirm, consent)
    if errors:
        for message in errors:
            st.error(message)
        return
    start_session(user)


def render_auth_page() -> None:
    st.html(CSS + '<div class="auth-hero"><strong>Smart Weekly Scheduling</strong>'
                  '<span>Đăng nhập để lập lịch tuần và lưu dữ liệu riêng của bạn</span></div>')
    _, middle, _ = st.columns([1, 1.6, 1])
    with middle, st.container(border=True, key="auth_card"):
        login_tab, register_tab = st.tabs(["Đăng nhập", "Đăng ký"])
        with login_tab:
            _login_tab()
        with register_tab:
            _register_tab()
