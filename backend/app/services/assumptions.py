from __future__ import annotations

from fastapi import HTTPException
from pydantic import ValidationError

from ..api.deps import Ctx
from ..engine import models as em
from ..models import AssumptionSet
from .plan_builder import _deep_merge, active_assumptions


def save_assumptions(ctx: Ctx, patch: dict, note: str | None = None, correlations: dict | None = None) -> AssumptionSet:
    """Assumptions are never overwritten: each change is stored as a new version."""
    plan = ctx.plan()
    current = active_assumptions(ctx.db, plan)
    merged = _deep_merge(current.payload, patch)
    try:
        validated = em.Assumptions.model_validate(merged)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(x) for x in first["loc"])
        raise HTTPException(422, f"{where}: {first['msg']}") from exc
    row = AssumptionSet(household_id=ctx.hid, plan_id=plan.id, version=current.version + 1,
                        payload=validated.model_dump(mode="json"),
                        correlations=correlations if correlations is not None else current.correlations,
                        note=note, created_by=ctx.user.id)
    ctx.db.add(row)
    ctx.db.flush()
    ctx.log("assumptions.update", "assumptions", row.id, {"version": row.version, "changed": sorted(patch)})
    return row
