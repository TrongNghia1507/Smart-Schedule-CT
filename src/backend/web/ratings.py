from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from user_portal import repository, rating_schema as schema
from user_portal.metrics import criterion_facts

from .auth import Session, planner
from .errors import WebError, not_found
from .storage import database, db_path

router = APIRouter(prefix="/ratings", tags=["ratings"])
Score = Annotated[int, Field(ge=1, le=5, strict=True)]


class Criterion(BaseModel):
    satisfaction: Score | None
    importance: Score


class Rating(BaseModel):
    criteria: dict[str, Criterion]
    tradeoffs: dict[str, Annotated[int, Field(ge=-2, le=2, strict=True)]]
    overall: Score
    adoption: str
    vs_manual: Score | None
    nps: int = Field(ge=0, le=10, strict=True)
    conflict_clarity: Score | None = None
    problems: list[str]
    comment_good: str = Field(default="", max_length=600)
    comment_improve: str = Field(default="", max_length=600)


def finalized(user_id, key):
    with database() as conn:
        row = conn.execute(
            """SELECT f.week_start, COALESCE(w.metrics, r.metrics_json) AS metrics
               FROM finalized_schedules f
               LEFT JOIN web_finalized w USING (user_id, schedule_key)
               LEFT JOIN ratings r USING (user_id, schedule_key)
               WHERE f.user_id=? AND f.schedule_key=?""", (user_id, key)
        ).fetchone()
    if not row or not row["metrics"]:
        raise not_found()
    return row["week_start"], json.loads(row["metrics"])


@router.get("/schema")
def form_schema(current: Session = Depends(planner)):
    return {
        "criteria": schema.CRITERIA, "tradeoffs": schema.TRADEOFFS,
        "tradeoff_labels": schema.TRADEOFF_LABELS, "adoption": schema.ADOPTION_OPTIONS,
        "vs_manual": schema.VS_MANUAL_LABELS, "no_baseline": schema.NO_BASELINE, "problems": schema.PROBLEMS,
    }


@router.get("/{key}")
def detail(key: str, current: Session = Depends(planner)):
    _, metrics = finalized(current.user.id, key)
    old = repository.get_rating(current.user.id, key, db_path())
    if old:
        for field in ("criteria", "tradeoffs", "problems"):
            old[field] = json.loads(old.pop(f"{field}_json"))
        old.pop("metrics_json")
    return {"rating": old, "metrics": metrics, "facts": criterion_facts(metrics)}


@router.put("/{key}")
def update(key: str, data: Rating, current: Session = Depends(planner)):
    week, metrics = finalized(current.user.id, key)
    if (
        set(data.criteria) != {item["key"] for item in schema.CRITERIA}
        or set(data.tradeoffs) != {item["key"] for item in schema.TRADEOFFS}
        or data.adoption not in schema.ADOPTION_OPTIONS
        or set(data.problems) - set(schema.PROBLEMS)
        or bool(metrics["options_applied"]) != (data.conflict_clarity is not None)
    ):
        raise WebError(422, "RATING_INVALID", "Hãy trả lời đầy đủ các mục trong biểu mẫu đánh giá.")
    payload = data.model_dump()
    payload["problems"] = list(dict.fromkeys(data.problems))
    repository.save_rating(current.user.id, key, week, payload, metrics, db_path())
    return detail(key, current)
