"""Plan assumptions and every calculation: projection, Monte Carlo, taxes, stress tests, scenarios."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from ..engine import models as em
from ..engine.montecarlo import correlation_matrix
from ..engine.roth import STRATEGY_LABELS
from ..engine.stress import CustomStress, list_historical, run_custom, run_historical, run_sequence
from ..engine.taxrules import available_years, load_rules, state_tax_data
from ..models import AssetClass, AssumptionSet, MonteCarloRun, RothStrategy, Scenario
from ..services import insights as insights_svc
from ..services import runs
from ..services.assumptions import save_assumptions
from ..services.plan_builder import ScenarioOverrides, active_assumptions
from .data import In, row_dict
from .deps import Ctx, get_ctx, get_writer

router = APIRouter(tags=["planning"])

DEFAULT_SEED = 20260101
LEVER_PATHS = 500


# ----------------------------------------------------------------------------- plan & assumptions


@router.get("/plan")
def get_plan(ctx: Ctx = Depends(get_ctx)):
    plan = ctx.plan()
    aset = active_assumptions(ctx.db, plan)
    classes = ctx.db.scalars(select(AssetClass).where(AssetClass.household_id == ctx.hid)
                             .order_by(AssetClass.sort_order))
    return {
        "plan": row_dict(plan),
        "assumptions": aset.payload,
        "assumption_version": aset.version,
        "assumption_note": aset.note,
        "assumption_saved_at": aset.created_at.isoformat(),
        "defaults": em.Assumptions().model_dump(mode="json"),
        "asset_classes": [row_dict(c) for c in classes],
        "correlations": aset.correlations or em.default_correlations(),
        "strategy_labels": STRATEGY_LABELS,
        "tax_rules": [{"tax_year": y, "version": load_rules(y).version, "sources": load_rules(y).raw["sources"]}
                      for y in available_years()],
        "state_tax_note": state_tax_data()["note"],
        "engine_version": em.ENGINE_VERSION,
    }


class AssumptionsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    changes: dict
    note: str | None = Field(None, max_length=300)


@router.patch("/plan/assumptions")
def update_assumptions(body: AssumptionsIn, ctx: Ctx = Depends(get_writer)):
    row = save_assumptions(ctx, body.changes, body.note)
    return {"assumptions": row.payload, "assumption_version": row.version}


@router.get("/plan/assumptions/history")
def assumptions_history(ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.scalars(select(AssumptionSet).where(AssumptionSet.plan_id == ctx.plan().id)
                          .order_by(AssumptionSet.version.desc()).limit(50))
    return [{"version": r.version, "note": r.note, "saved_at": r.created_at.isoformat(), "payload": r.payload}
            for r in rows]


class PlanIn(In):
    name: str | None = Field(None, min_length=1, max_length=120)
    start_year: int | None = Field(None, ge=2025, le=2100)


@router.patch("/plan")
def update_plan(body: PlanIn, ctx: Ctx = Depends(get_writer)):
    plan = ctx.plan()
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(plan, k, v)
    ctx.log("plan.update", "plan", plan.id)
    return row_dict(plan)


class AssetClassIn(In):
    name: str = Field(min_length=1, max_length=80)
    expected_return: float = Field(ge=-0.2, le=0.3)
    volatility: float = Field(ge=0, le=1)
    income_yield: float = Field(0, ge=0, le=0.2)
    qualified_ratio: float = Field(0, ge=0, le=1)


@router.put("/plan/asset-classes/{key}")
def update_asset_class(key: str, body: AssetClassIn, ctx: Ctx = Depends(get_writer)):
    row = ctx.db.scalar(select(AssetClass).where(AssetClass.household_id == ctx.hid, AssetClass.key == key))
    if row is None:
        raise HTTPException(404, "Not found.")
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    ctx.log("asset_class.update", "asset_class", row.id, body.model_dump())
    return row_dict(row)


@router.post("/plan/asset-classes/reset")
def reset_asset_classes(ctx: Ctx = Depends(get_writer)):
    defaults = {c.key: c for c in em.default_asset_classes()}
    for row in ctx.db.scalars(select(AssetClass).where(AssetClass.household_id == ctx.hid)):
        d = defaults.get(row.key)
        if d:
            for k in ("name", "expected_return", "volatility", "income_yield", "qualified_ratio", "proxy"):
                setattr(row, k, getattr(d, k))
    ctx.log("asset_class.reset")
    return {"ok": True}


class CorrelationsIn(BaseModel):
    correlations: dict[str, dict[str, float]]


@router.put("/plan/correlations")
def update_correlations(body: CorrelationsIn, ctx: Ctx = Depends(get_writer)):
    plan_input, _, _, _ = runs.resolve(ctx)
    try:
        correlation_matrix(plan_input.model_copy(update={"correlations": body.correlations}))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    row = save_assumptions(ctx, {}, "Correlations changed", correlations=body.correlations)
    return {"assumption_version": row.version}


@router.get("/plan/input")
def plan_input_snapshot(scenario_id: str | None = None, ctx: Ctx = Depends(get_ctx)):
    """Exactly what the engine receives - for full transparency."""
    plan_input, notes, _, version = runs.resolve(ctx, scenario_id)
    return {"input": plan_input.model_dump(mode="json"), "input_hash": plan_input.content_hash(),
            "assumption_version": version, "notes": notes}


# ----------------------------------------------------------------------------- calculations


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str | None = None


@router.post("/projection")
def run_projection(body: RunIn | None = None, ctx: Ctx = Depends(get_ctx)):
    return runs.projection(ctx, scenario_id=body.scenario_id if body else None)


class MonteCarloIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str | None = None
    n_paths: int = Field(1000, ge=100)
    seed: int = Field(DEFAULT_SEED, ge=0, le=2_147_483_647)
    distribution: Literal["normal", "student_t", "laplace"] = "normal"
    degrees_of_freedom: float = Field(5.0, gt=2, le=100)


@router.post("/monte-carlo")
def run_mc(body: MonteCarloIn | None = None, ctx: Ctx = Depends(get_ctx)):
    b = body or MonteCarloIn()
    return runs.monte_carlo(ctx, n_paths=b.n_paths, seed=b.seed, distribution=b.distribution,
                            df=b.degrees_of_freedom, scenario_id=b.scenario_id)


@router.get("/monte-carlo/runs")
def mc_runs(ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.scalars(select(MonteCarloRun).where(MonteCarloRun.household_id == ctx.hid)
                          .order_by(MonteCarloRun.created_at.desc()).limit(30))
    return [{"id": r.id, "created_at": r.created_at.isoformat(), "seed": r.seed, "n_paths": r.n_paths,
             "distribution": r.distribution, "success_probability": r.success_probability,
             "input_hash": r.input_hash, "scenario_id": r.scenario_id, "duration_ms": r.duration_ms,
             "assumption_version": r.assumption_version} for r in rows]


@router.get("/monte-carlo/runs/{run_id}")
def mc_run(run_id: str, ctx: Ctx = Depends(get_ctx)):
    r = ctx.owned(MonteCarloRun, run_id)
    return {**r.result, "id": r.id, "created_at": r.created_at.isoformat(), "input_snapshot": r.input_snapshot}


@router.get("/insights")
def get_insights(ctx: Ctx = Depends(get_ctx)):
    """Plain-English summary for the home page."""
    plan_input, notes, _, _ = runs.resolve(ctx)
    proj = runs.projection(ctx)
    mc = runs.monte_carlo(ctx, n_paths=1000, seed=DEFAULT_SEED)
    out = insights_svc.build(plan_input, proj, mc)
    out["notes"] = notes + proj.get("warnings", [])
    out["simulation"] = {"seed": mc["meta"]["seed"], "n_paths": mc["n_paths"],
                         "distribution": mc["meta"]["distribution"]}
    out["chart"] = {
        "years": proj["years"],
        "price_index": proj["price_index"],
        "projection_real": [round(r["portfolio"] / r["price_index"], 2) for r in proj["rows"]],
        "p10_real": mc["portfolio_real"]["p10"],
        "p50_real": mc["portfolio_real"]["p50"],
        "p90_real": mc["portfolio_real"]["p90"],
    }
    out["meta"] = proj["meta"]
    return out


@router.get("/insights/levers")
def levers(ctx: Ctx = Depends(get_ctx)):
    """What would help most? A few standard what-ifs, each run through the simulation."""
    from ..ai.tools import WhatIf, to_overrides
    base = runs.monte_carlo(ctx, n_paths=LEVER_PATHS, seed=DEFAULT_SEED, store=False)
    tests = [
        ("retire_later", "Retire 2 years later", WhatIf(retire_years_later=2)),
        ("spend_less", "Spend 10% less", WhatIf(spending_change_pct=-10)),
        ("claim_70", "Start Social Security at 70", WhatIf(ss_claim_age=70)),
        ("spend_more", "Spend 10% more", WhatIf(spending_change_pct=10)),
    ]
    out = []
    for key, label, w in tests:
        try:
            ov = to_overrides(ctx, w)
            mc = runs.monte_carlo(ctx, n_paths=LEVER_PATHS, seed=DEFAULT_SEED, overrides=ov, store=False)
        except HTTPException:
            continue
        out.append({"key": key, "label": label, "success_probability": mc["success_probability"],
                    "change": round(mc["success_probability"] - base["success_probability"], 4),
                    "overrides": ov.model_dump(exclude_defaults=True) if ov else {}})
    return {"baseline": base["success_probability"], "n_paths": LEVER_PATHS, "seed": DEFAULT_SEED,
            "levers": out,
            "note": f"Each test uses {LEVER_PATHS} simulated futures with the same seed, so results are "
                    f"directly comparable. These are illustrations, not recommendations."}


# ----------------------------------------------------------------------------- taxes


class RothIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str | None = None
    weights: dict[Literal["lifetime_cost", "after_tax_wealth", "beneficiary_value"], float] | None = None


@router.post("/roth/optimize")
def roth_optimize(body: RothIn | None = None, ctx: Ctx = Depends(get_ctx)):
    b = body or RothIn()
    return runs.roth(ctx, b.weights, b.scenario_id)


class RothApplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy_id: str
    key: str


@router.post("/roth/apply")
def roth_apply(body: RothApplyIn, ctx: Ctx = Depends(get_writer)):
    """Save one of the compared strategies into the plan (an explicit user action)."""
    strat = ctx.owned(RothStrategy, body.strategy_id)
    cand = next((c for c in strat.result["candidates"] if c["key"] == body.key), None)
    if cand is None:
        raise HTTPException(404, "That strategy is not part of this comparison.")
    row = save_assumptions(ctx, {"roth_conversion": cand["conversion"]}, note=f"Roth strategy: {cand['label']}")
    strat.applied_key = body.key
    ctx.log("roth.apply", "roth_strategy", strat.id, {"key": body.key})
    return {"assumption_version": row.version, "roth_conversion": row.payload["roth_conversion"]}


@router.post("/withdrawal-strategies/compare")
def strategy_compare(body: RunIn | None = None, ctx: Ctx = Depends(get_ctx)):
    return runs.strategies(ctx, body.scenario_id if body else None)


# ----------------------------------------------------------------------------- stress tests


@router.get("/stress/historical")
def historical(ctx: Ctx = Depends(get_ctx)):
    return list_historical()


class StressIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["historical", "custom", "sequence"]
    scenario_id: str | None = None
    key: str | None = None
    start_year: int | None = None
    custom: CustomStress | None = None
    years: int = Field(5, ge=1, le=15)
    severity: float = Field(1.0, gt=0, le=3)
    order: Literal["bad_first", "good_first"] = "bad_first"


@router.post("/stress/run")
def stress_run(body: StressIn, ctx: Ctx = Depends(get_ctx)):
    plan_input, notes, _, _ = runs.resolve(ctx, body.scenario_id)
    try:
        if body.kind == "historical":
            out = run_historical(plan_input, body.key or "", body.start_year)
        elif body.kind == "custom":
            custom = body.custom or CustomStress()
            if body.start_year and custom.start_year is None:
                custom = custom.model_copy(update={"start_year": body.start_year})
            out = run_custom(plan_input, custom)
        else:
            out = run_sequence(plan_input, body.years, body.severity, body.start_year, body.order)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, str(exc)) from exc
    ctx.log("stress.run", detail={"kind": body.kind, "key": body.key})
    return {**out, "notes": notes}


# ----------------------------------------------------------------------------- scenarios


class ScenarioIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(None, max_length=500)
    overrides: ScenarioOverrides = ScenarioOverrides()


def scenario_out(s: Scenario) -> dict:
    return {"id": s.id, "name": s.name, "description": s.description, "overrides": s.overrides,
            "created_at": s.created_at.isoformat(), "updated_at": s.updated_at.isoformat()}


def _validate_scenario(ctx: Ctx, body: ScenarioIn) -> None:
    try:
        runs.resolve(ctx, overrides=body.overrides)
    except HTTPException as exc:
        raise HTTPException(422, f"This scenario cannot be calculated: {exc.detail}") from exc


@router.get("/scenarios")
def list_scenarios(ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.scalars(select(Scenario).where(Scenario.household_id == ctx.hid).order_by(Scenario.created_at))
    return {"baseline": {"id": None, "name": "Current plan", "protected": True,
                         "description": "Your saved plan. Scenarios never change it."},
            "scenarios": [scenario_out(s) for s in rows]}


@router.post("/scenarios", status_code=201)
def create_scenario(body: ScenarioIn, ctx: Ctx = Depends(get_writer)):
    _validate_scenario(ctx, body)
    s = Scenario(household_id=ctx.hid, plan_id=ctx.plan().id, name=body.name, description=body.description,
                 overrides=body.overrides.model_dump(mode="json"))
    ctx.db.add(s)
    ctx.db.flush()
    ctx.log("scenario.create", "scenario", s.id)
    return scenario_out(s)


@router.put("/scenarios/{scenario_id}")
def update_scenario(scenario_id: str, body: ScenarioIn, ctx: Ctx = Depends(get_writer)):
    s = ctx.owned(Scenario, scenario_id)
    _validate_scenario(ctx, body)
    s.name, s.description, s.overrides = body.name, body.description, body.overrides.model_dump(mode="json")
    ctx.log("scenario.update", "scenario", s.id)
    return scenario_out(s)


@router.delete("/scenarios/{scenario_id}", status_code=204)
def delete_scenario(scenario_id: str, ctx: Ctx = Depends(get_writer)):
    ctx.db.delete(ctx.owned(Scenario, scenario_id))
    ctx.log("scenario.delete", "scenario", scenario_id)
    return Response(status_code=204)


class CompareIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_ids: list[str] = Field(default_factory=list, max_length=6)
    n_paths: int = Field(1000, ge=100, le=5000)
    seed: int = DEFAULT_SEED


@router.post("/scenarios/compare")
def compare_scenarios(body: CompareIn, ctx: Ctx = Depends(get_ctx)):
    """Current plan and chosen scenarios side by side (same seed for a fair comparison)."""
    columns = []
    for sid in [None, *body.scenario_ids]:
        proj = runs.projection(ctx, scenario_id=sid)
        mc = runs.monte_carlo(ctx, n_paths=body.n_paths, seed=body.seed, scenario_id=sid)
        name = "Current plan" if sid is None else ctx.owned(Scenario, sid).name
        columns.append({
            "scenario_id": sid, "name": name, "is_baseline": sid is None,
            "summary": proj["summary"], "success_probability": mc["success_probability"],
            "ending_portfolio_real": mc["ending_portfolio_real"],
            "years": proj["years"],
            "portfolio_real": [round(r["portfolio"] / r["price_index"], 2) for r in proj["rows"]],
            "spending_real": [round(r["spending_total"] / r["price_index"], 2) for r in proj["rows"]],
            "input_hash": proj["meta"]["plan_hash"],
        })
    return {"columns": columns, "seed": body.seed, "n_paths": body.n_paths,
            "note": "All columns use the same simulated futures (same seed), so differences come only from "
                    "the changes in each scenario."}
