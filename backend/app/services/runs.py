"""Run calculations for a household and store them with their input snapshot."""
from __future__ import annotations

import time

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from ..api.deps import Ctx
from ..config import get_settings
from ..engine import models as em
from ..engine.montecarlo import run_monte_carlo
from ..engine.projection import project
from ..engine.roth import compare_withdrawal_strategies, optimize_roth
from ..models import MonteCarloRun, ProjectionResult, RothStrategy, Scenario
from .plan_builder import ScenarioOverrides, build_plan_input


def resolve(ctx: Ctx, scenario_id: str | None = None,
            overrides: ScenarioOverrides | None = None) -> tuple[em.PlanInput, list[str], str, int]:
    """Build the plan input for the baseline, a stored scenario or ad-hoc overrides."""
    plan = ctx.plan()
    name = None
    if scenario_id:
        scenario = ctx.owned(Scenario, scenario_id)
        overrides = ScenarioOverrides.model_validate(scenario.overrides or {})
        name = scenario.name
    try:
        plan_input, notes, version = build_plan_input(ctx.db, ctx.household, plan, overrides, name=name)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise HTTPException(422, f"The plan data is not complete: {first['msg']}") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return plan_input, notes, plan.id, version


def projection(ctx: Ctx, scenario_id: str | None = None, overrides: ScenarioOverrides | None = None,
               store: bool = True) -> dict:
    plan_input, notes, plan_id, version = resolve(ctx, scenario_id, overrides)
    h = plan_input.content_hash()
    if store and overrides is None:
        cached = ctx.db.scalars(
            select(ProjectionResult).where(
                ProjectionResult.household_id == ctx.hid, ProjectionResult.input_hash == h,
                ProjectionResult.kind == "projection", ProjectionResult.engine_version == em.ENGINE_VERSION,
                ProjectionResult.scenario_id == scenario_id if scenario_id else ProjectionResult.scenario_id.is_(None),
            ).order_by(ProjectionResult.created_at.desc())).first()
        if cached:
            return {**cached.result, "id": cached.id, "created_at": cached.created_at.isoformat(),
                    "notes": notes, "cached": True}
    result = project(plan_input)
    out = {**result, "notes": notes, "cached": False}
    if store and overrides is None:
        row = ProjectionResult(household_id=ctx.hid, plan_id=plan_id, scenario_id=scenario_id, kind="projection",
                               input_hash=h, input_snapshot=plan_input.model_dump(mode="json"),
                               engine_version=em.ENGINE_VERSION, assumption_version=version,
                               summary=result["summary"], result=result)
        ctx.db.add(row)
        ctx.db.flush()
        ctx.log("projection.run", "projection_result", row.id, {"input_hash": h, "scenario_id": scenario_id})
        out.update(id=row.id, created_at=row.created_at.isoformat())
    return out


def monte_carlo(ctx: Ctx, *, n_paths: int = 1000, seed: int = 20260101, distribution: str = "normal",
                df: float = 5.0, scenario_id: str | None = None, overrides: ScenarioOverrides | None = None,
                store: bool = True) -> dict:
    cap = get_settings().max_monte_carlo_paths
    if not 100 <= n_paths <= cap:
        raise HTTPException(422, f"Number of simulations must be between 100 and {cap:,}.")
    plan_input, notes, plan_id, version = resolve(ctx, scenario_id, overrides)
    h = plan_input.content_hash()
    if store and overrides is None:
        cached = ctx.db.scalars(
            select(MonteCarloRun).where(
                MonteCarloRun.household_id == ctx.hid, MonteCarloRun.input_hash == h, MonteCarloRun.seed == seed,
                MonteCarloRun.n_paths == n_paths, MonteCarloRun.distribution == distribution,
                MonteCarloRun.engine_version == em.ENGINE_VERSION,
                MonteCarloRun.scenario_id == scenario_id if scenario_id else MonteCarloRun.scenario_id.is_(None),
            ).order_by(MonteCarloRun.created_at.desc())).first()
        if cached and (distribution != "student_t" or cached.degrees_of_freedom == df):
            return {**cached.result, "id": cached.id, "created_at": cached.created_at.isoformat(),
                    "notes": notes, "cached": True}
    started = time.perf_counter()
    try:
        result = run_monte_carlo(plan_input, n_paths=n_paths, seed=seed, distribution=distribution, df=df)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    ms = int((time.perf_counter() - started) * 1000)
    out = {**result, "notes": notes, "cached": False, "duration_ms": ms}
    if store and overrides is None:
        row = MonteCarloRun(household_id=ctx.hid, plan_id=plan_id, scenario_id=scenario_id, seed=seed,
                            n_paths=n_paths, distribution=distribution,
                            degrees_of_freedom=df if distribution == "student_t" else None, input_hash=h,
                            input_snapshot=plan_input.model_dump(mode="json"), engine_version=em.ENGINE_VERSION,
                            numpy_version=result["meta"]["numpy_version"], assumption_version=version,
                            success_probability=result["success_probability"], duration_ms=ms, result=result)
        ctx.db.add(row)
        ctx.db.flush()
        ctx.log("monte_carlo.run", "monte_carlo_run", row.id,
                {"input_hash": h, "seed": seed, "n_paths": n_paths, "distribution": distribution})
        out.update(id=row.id, created_at=row.created_at.isoformat())
    return out


def roth(ctx: Ctx, weights: dict[str, float] | None = None, scenario_id: str | None = None) -> dict:
    plan_input, notes, plan_id, _ = resolve(ctx, scenario_id)
    result = optimize_roth(plan_input, weights)
    row = RothStrategy(household_id=ctx.hid, plan_id=plan_id, scenario_id=scenario_id,
                       input_hash=plan_input.content_hash(), input_snapshot=plan_input.model_dump(mode="json"),
                       weights=result["weights"], recommended_key=result["recommended_key"], result=result)
    ctx.db.add(row)
    ctx.db.flush()
    ctx.log("roth.optimize", "roth_strategy", row.id, {"recommended": result["recommended_key"]})
    current = plan_input.assumptions.roth_conversion.model_dump()
    return {**result, "id": row.id, "notes": notes, "current_conversion": current,
            "plan_hash": plan_input.content_hash()}


def strategies(ctx: Ctx, scenario_id: str | None = None) -> dict:
    plan_input, notes, _, _ = resolve(ctx, scenario_id)
    return {**compare_withdrawal_strategies(plan_input), "notes": notes, "plan_hash": plan_input.content_hash()}
