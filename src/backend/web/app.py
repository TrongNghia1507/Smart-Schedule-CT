from __future__ import annotations
import pymysql
import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from conflict_resolver.api import analyze_conflict as analyze_legacy, health as legacy_health
from conflict_resolver.errors import SolverInconclusive
from conflict_resolver.models import ConflictReport

from . import admin, auth, draft, history, plans, ratings
from .errors import WebError
from .locale import localize, web_language
from .storage import database, initialize

logger = logging.getLogger(__name__)
WEB_DIST = Path(os.environ.get("SCHEDULE_WEB_DIST") or Path(__file__).resolve().parents[3] / "apps/web/dist")


@asynccontextmanager
async def lifespan(_app):
    initialize()
    yield


app = FastAPI(title="Smart Schedule CT", version="1.0.0", lifespan=lifespan)
for router in (auth.router, draft.router, plans.router, history.router, ratings.router, admin.router):
    app.include_router(router, prefix="/api/v1")


def error(status, code, message, issues=None):
    return JSONResponse(status_code=status, content=jsonable_encoder(
        {"code": code, "message": localize(message), "issues": issues or []}
    ))


@app.middleware("http")
async def api_cache(request: Request, call_next):
    raw_language = request.headers.get("accept-language", "").split(",")[0].strip().lower()
    token = web_language.set("en" if raw_language.startswith("en") else "vi")
    try:
        response = await call_next(request)
    finally:
        web_language.reset(token)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(WebError)
async def web_error(_request, exc):
    return error(exc.status, exc.code, exc.message, exc.issues)


@app.exception_handler(SolverInconclusive)
async def solver_error(request, exc):
    if request.url.path == "/conflicts/analyze":
        return JSONResponse(status_code=503, content={"detail": str(exc)})
    return error(503, "SOLVER_INCONCLUSIVE", str(exc))


@app.exception_handler(ValueError)
async def value_error(_request, exc):
    return error(422, "INVALID_INPUT", str(exc))


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    if request.url.path == "/conflicts/analyze":
        return await request_validation_exception_handler(request, exc)
    issues = [{"field": ".".join(map(str, item["loc"])), "message": item["msg"]} for item in exc.errors()]
    return error(422, "INVALID_REQUEST", "Dữ liệu gửi lên không hợp lệ.", issues)


@app.exception_handler(HTTPException)
async def http_error(_request, exc):
    response = error(exc.status_code, "HTTP_ERROR", exc.detail)
    if exc.headers:
        response.headers.update(exc.headers)
    return response


@app.get("/api/v1/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/ready")
def ready():
    try:
        with database() as conn:
            conn.execute("SELECT 1 FROM web_drafts LIMIT 1").fetchone()
    except (OSError, sqlite3.Error,pymysql.Error):
        logger.exception("Database readiness failed")
        return error(503, "NOT_READY", "Cơ sở dữ liệu chưa sẵn sàng.")
    return {"status": "ready"}


# Preserve the original integration endpoint and its response contract.
app.add_api_route("/health", legacy_health, methods=["GET"], include_in_schema=False)
app.add_api_route("/conflicts/analyze", analyze_legacy,
                  methods=["POST"], response_model=ConflictReport,
                  include_in_schema=False)


@app.get("/", include_in_schema=False)
@app.get("/app", include_in_schema=False)
def root(request: Request):
    return RedirectResponse("/app/" + (f"?{request.url.query}" if request.url.query else ""))


if (WEB_DIST / "assets").is_dir():
    app.mount("/app/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")


@app.get("/app/{path:path}", include_in_schema=False)
def frontend(path: str):
    if path.startswith("assets/") or "." in path.rsplit("/", 1)[-1]:
        return error(404, "NOT_FOUND", "Không tìm thấy tệp.")
    index = WEB_DIST / "index.html"
    if not index.is_file():
        return error(503, "FRONTEND_NOT_BUILT", "Hãy chạy npm --prefix apps/web run build.")
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
