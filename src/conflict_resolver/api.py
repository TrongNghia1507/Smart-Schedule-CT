from fastapi import FastAPI

from .ai.advisor import get_settings
from .models import ConflictContext, ConflictReport
from .resolver import resolve
from .scheduler import ReferenceScheduler


app = FastAPI(
    title="Weekly Planner Conflict API",
    version="0.1.0",
)

scheduler = ReferenceScheduler()


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "engine": scheduler.name,
    }


@app.post(
    "/conflicts/analyze",
    response_model=ConflictReport,
)
async def analyze_conflict(context: ConflictContext):
    return await resolve(
        context,
        scheduler,
        get_settings(),
    )