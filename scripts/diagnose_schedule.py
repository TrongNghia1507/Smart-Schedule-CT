import json
import time
from pathlib import Path

from conflict_resolver.planning import context_from_snapshot, PlanningSession
from conflict_resolver.scheduler import CoreScheduler

snapshot = Path(__file__).resolve().parents[1] / "examples" / "input_snapshot.json"
ctx = context_from_snapshot(json.loads(snapshot.read_text(encoding="utf-8")))
s = PlanningSession(ctx)

t = time.time(); base = s.plan()
print("baseline:", base.status, base.solver_status, f"{time.time()-t:.1f}s")
print("chưa xếp:", base.unscheduled)

target = next(t.id for t in ctx.tasks if t.name.startswith("SP"))
kept = {c.task_id for c in base.chunks} | {target}
scoped = ctx.model_copy(deep=True)
scoped.tasks = [t for t in scoped.tasks if t.id in kept]
print("provably_infeasible:", CoreScheduler.provably_infeasible(scoped))

for limit in (1, 5, 20):
    t = time.time()
    r = CoreScheduler(time_limit=limit).plan(scoped)
    print(f"limit={limit}s ->", r.status, r.solver_status, f"{time.time()-t:.1f}s")
