from __future__ import annotations

import csv
import io
from collections import Counter
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field

from backend.clock import VN_TZ
from user_portal import auth, repository, rating_schema

from .auth import COOKIE, Session, admin
from .draft import export_file
from .errors import WebError
from .storage import database, db_path, secure_cookies

router = APIRouter(prefix="/admin", tags=["admin"])


def local(stamp):
    return datetime.fromisoformat(stamp).astimezone(VN_TZ).strftime("%d/%m/%Y %H:%M") if stamp else "—"


def csv_value(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def csv_response(rows, filename):
    out = io.StringIO()
    if rows:
        writer = csv.DictWriter(out, fieldnames=list(dict.fromkeys(key for row in rows for key in row)))
        writer.writeheader()
        writer.writerows({key: csv_value(value) for key, value in row.items()} for row in rows)
    return export_file(out.getvalue().encode("utf-8-sig"), filename, "text/csv")


def users_view(data):
    count = Counter(row["user_id"] for row in data["ratings"])
    keys = ("id", "username", "full_name", "user_group", "email", "created_at", "last_login_at", "login_count")
    return [{**{key: user[key] for key in keys}, "ratings": count[user["id"]]} for user in data["users"]]


@router.get("/overview")
def overview(_current: Session = Depends(admin)):
    data = repository.overview(db_path())
    data["users"] = users_view(data)
    for rating in data["ratings"]:
        for field in ("criteria_json", "tradeoffs_json", "problems_json", "metrics_json"):
            rating.pop(field, None)
    return data


@router.get("/ratings.csv")
def ratings_export(
    score: Annotated[list[int] | None, Query()] = None, group: Annotated[list[str] | None, Query()] = None,
    empty: bool = False, _current: Session = Depends(admin),
):
    if empty:
        return csv_response([], "ratings.csv")
    data = repository.overview(db_path())
    rows = []
    for rating in data["ratings"]:
        if score is not None and rating["overall"] not in score:
            continue
        if group is not None and (rating["user_group"] or "—") not in group:
            continue
        row = {
            "Người dùng": rating["username"], "Họ tên": rating["full_name"], "Nhóm": rating["user_group"],
            "Tuần": rating["week_start"], "Cập nhật": local(rating["updated_at"]),
            "Hài lòng chung": rating["overall"], "Giới thiệu (0-10)": rating["nps"], "Cách dùng": rating["adoption"],
            "So với tự xếp": rating["vs_manual"], "Độ dễ hiểu phương án": rating["conflict_clarity"],
        }
        for item in rating_schema.CRITERIA:
            value = rating["criteria"].get(item["key"], {})
            row[f"{item['short']} – hài lòng"] = value.get("satisfaction")
            row[f"{item['short']} – quan trọng"] = value.get("importance")
        for item in rating_schema.TRADEOFFS:
            row[f"Đánh đổi {item['key']}"] = rating["tradeoffs"].get(item["key"])
        row.update({"Vấn đề": "; ".join(rating["problems"]), "Điều tốt": rating["comment_good"],
                    "Cần cải thiện": rating["comment_improve"]})
        row.update({f"metric_{key}": value for key, value in rating["metrics"].items()})
        rows.append(row)
    return csv_response(rows, "ratings.csv")


@router.get("/users.csv")
def users_export(_current: Session = Depends(admin)):
    rows = [{
        "Tên đăng nhập": u["username"], "Họ tên": u["full_name"], "Nhóm": u["user_group"],
        "Email": u["email"], "Ngày đăng ký": local(u["created_at"]),
        "Đăng nhập gần nhất": local(u["last_login_at"]), "Số lần đăng nhập": u["login_count"],
        "Số đánh giá": u["ratings"],
    } for u in users_view(repository.overview(db_path()))]
    return csv_response(rows, "users.csv")


class PasswordChange(BaseModel):
    current: str = Field(max_length=256)
    new: str = Field(max_length=256)
    confirm: str = Field(max_length=256)


@router.post("/password", status_code=204)
def change_password(data: PasswordChange, request: Request, current: Session = Depends(admin)):
    error = auth.change_admin_password(data.current, data.new, data.confirm, db_path())
    if error:
        raise WebError(422, "PASSWORD_INVALID", error)
    with database(write=True) as conn:
        conn.execute("DELETE FROM web_sessions WHERE user_id=?", (current.user.id,))
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, secure=secure_cookies() or request.url.scheme == "https", httponly=True)
    return response
