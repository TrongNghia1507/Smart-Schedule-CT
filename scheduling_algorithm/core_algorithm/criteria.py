from __future__ import annotations
from typing import Callable
from context import Ctx

CRITERIA: dict[str, Callable[[Ctx], tuple]] = {}


def register(name: str):
    def decorator(fn):
        CRITERIA[name] = fn
        return fn
    return decorator

@register("max_priority")
def max_priority(ctx: Ctx):
    """Maximize total priority of scheduled tasks."""
    score = sum(t.priority * ctx.present[t.id] for t in ctx.tasks)
    bound = sum(t.priority for t in ctx.tasks)
    return score, max(1, bound)


@register("max_count")
def max_count(ctx: Ctx):
    """Maximize the number of scheduled tasks."""
    score = sum(ctx.present[t.id] for t in ctx.tasks)
    bound = len(ctx.tasks)
    return score, max(1, bound)


@register("early_finish")
def early_finish(ctx: Ctx):
    """Reward priority-weighted early completion; omitted tasks score zero."""
    horizon = ctx.cfg.horizon_slots
    cost = sum(
        t.priority * (
            ctx.finish[t.id] + horizon * (1 - ctx.present[t.id])
        )
        for t in ctx.tasks
    )
    bound = horizon * sum(t.priority for t in ctx.tasks)
    return bound - cost, max(1, bound)


@register("fewer_pieces")
def fewer_pieces(ctx: Ctx):
    """Minimize the total number of used chunks."""
    pieces = [c for t in ctx.tasks for c in ctx.chunks[t.id]]
    cost = sum(c.used for c in pieces)
    bound = len(pieces)
    return bound - cost, max(1, bound)
