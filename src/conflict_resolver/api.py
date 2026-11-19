from fastapi import FastAPI

from .ai.advisor import get_settings
from .models import ConflictContext, ConflictReport
from .resolver import resolve
from .scheduler import CoreScheduler
from fastapi.responses import JSONResponse
from .errors import SolverInconclusive

app = FastAPI(
    title="Weekly Planner Conflict API",
    version="0.1.0",
)

scheduler = CoreScheduler()


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
@app.exception_handler(SolverInconclusive)
async def solver_inconclusive_handler(request, exc):
    return JSONResponse(status_code=503, content={"detail": str(exc)})