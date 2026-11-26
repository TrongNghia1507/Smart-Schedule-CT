from __future__ import annotations

import hashlib
import secrets
from dataclasses import asdict, dataclass
from time import time

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from user_portal import auth

from .errors import WebError
from .storage import database, db_path, secure_cookies

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "schedule_session"
SESSION_SECONDS = 12 * 60 * 60


class Credentials(BaseModel):
    username: str = Field(max_length=30)
    password: str = Field(max_length=256)


class Registration(Credentials):
    full_name: str = Field(max_length=100)
    email: str = Field(default="", max_length=254)
    user_group: str = Field(max_length=50)
    confirm: str = Field(max_length=256)
    consent: bool


@dataclass(frozen=True)
class Session:
    user: auth.User
    token_hash: str
    csrf: str

    def public(self):
        return {"user": asdict(self.user), "csrf": self.csrf}


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def session(request: Request) -> Session:
    token = request.cookies.get(COOKIE)
    digest = token_hash(token) if token else ""
    with database() as conn:
        row = conn.execute(
            """SELECT u.id, u.username, u.full_name, u.role, s.csrf
               FROM web_sessions s JOIN users u ON u.id=s.user_id
               WHERE s.token_hash=? AND s.expires>?""",
            (digest, int(time())),
        ).fetchone()
    if not row:
        raise WebError(401, "AUTH_REQUIRED", "Hãy đăng nhập để tiếp tục.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        provided = request.headers.get("x-csrf-token", "")
        if not secrets.compare_digest(provided.encode(), row["csrf"].encode()):
            raise WebError(403, "CSRF_INVALID", "Phiên không hợp lệ. Hãy tải lại trang.")
    return Session(auth.User(row["id"], row["username"], row["full_name"], row["role"]), digest, row["csrf"])


def planner(current: Session = Depends(session)) -> Session:
    if current.user.is_admin:
        raise WebError(403, "ROLE_REQUIRED", "Tính năng này dành cho tài khoản lập lịch.")
    return current


def admin(current: Session = Depends(session)) -> Session:
    if not current.user.is_admin:
        raise WebError(403, "ROLE_REQUIRED", "Tính năng này dành cho quản trị viên.")
    return current


def start_session(user: auth.User, request: Request, response: Response) -> dict:
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    now = int(time())
    with database(write=True) as conn:
        conn.execute("DELETE FROM web_sessions WHERE expires<=?", (now,))
        if previous := request.cookies.get(COOKIE):
            conn.execute("DELETE FROM web_sessions WHERE token_hash=?", (token_hash(previous),))
        conn.execute("INSERT INTO web_sessions VALUES (?,?,?,?)", (token_hash(token), user.id, csrf, now + SESSION_SECONDS))
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                        secure=secure_cookies() or request.url.scheme == "https", samesite="lax")
    return Session(user, token_hash(token), csrf).public()


def require_json(request: Request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise WebError(415, "JSON_REQUIRED", "Yêu cầu phải gửi dưới dạng JSON.")


@router.get("/groups")
def groups():
    return auth.USER_GROUPS


@router.post("/login")
def login(data: Credentials, request: Request, response: Response):
    # JSON-only body and no credentialed cross-origin access keep login same-origin.
    require_json(request)
    if data.username.strip().lower() == auth.ADMIN_USERNAME:
        user, error = auth.login_admin(data.password, db_path())
    else:
        user, error = auth.login_user(data.username, data.password, db_path())
    if error:
        raise WebError(401, "LOGIN_FAILED", error)
    return start_session(user, request, response)


@router.post("/register", status_code=201)
def register(data: Registration, request: Request, response: Response):
    require_json(request)
    if data.user_group not in auth.USER_GROUPS:
        raise WebError(422, "INVALID_GROUP", "Chọn một nhóm người dùng.")
    user, errors = auth.register_user(**data.model_dump(), path=db_path())
    if errors:
        raise WebError(422, "REGISTRATION_INVALID", " ".join(errors))
    return start_session(user, request, response)


@router.get("/me")
def me(current: Session = Depends(session)):
    return current.public()


@router.post("/logout", status_code=204)
def logout(request: Request, current: Session = Depends(session)):
    with database(write=True) as conn:
        conn.execute("DELETE FROM web_sessions WHERE token_hash=?", (current.token_hash,))
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, secure=secure_cookies() or request.url.scheme == "https", httponly=True)
    return response
