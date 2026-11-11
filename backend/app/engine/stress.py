"""Stress tests: what happens to the plan if markets or prices misbehave.

Three kinds of test, all deterministic:
* historical:  replay the actual returns and inflation of a past episode,
               starting in a chosen plan year. These are records of the past,
               clearly labelled, and never a forecast.
* custom:      user-defined shocks (market drop, higher inflation, lower
               long-run returns, living longer).
* sequence:    the same average return, but with the bad years first (or last),
               to show sequence-of-returns risk.
Outside the shocked years the plan's expected returns and inflation apply.
"""
from __future__ import annotations

import json
from functools import cache

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from .models import PlanInput
from .projection import project
from .simulate import expected_returns
from .taxrules import DATA_DIR


@cache
def historical_data() -> dict:
    return json.loads((DATA_DIR / "historical_scenarios.json").read_text())


def list_historical() -> list[dict]:
    data = historical_data()
    return [{"key": s["key"], "name": s["name"], "plain": s["plain"], "years": s["years"],
             "data_note": data["note"], "as_of": data["as_of"]} for s in data["scenarios"]]


class CustomStress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "Custom stress test"
    start_year: int | None = Field(None, description="First shocked year. Default: first retirement year.")
    equity_return: float | None = Field(None, description="Return of stock-like assets in each shocked year.")
    bond_return: float | None = None
    cash_return: float | None = None
    duration_years: int = Field(1, ge=1, le=30)
    inflation: float | None = Field(None, description="Inflation during each shocked year.")
    inflation_years: int | None = Field(None, ge=1, le=60, description="Default: duration_years.")
    return_reduction: float = Field(0.0, ge=0, le=0.2, description="Lower every expected return, every year.")
    extra_years_of_life: int = Field(0, ge=0, le=20)


def default_start_year(plan: PlanInput) -> int:
    """First year in which everyone has retired (or the first plan year)."""
    return max(plan.start_year, max(m.retirement_year for m in plan.members))


def _base(plan: PlanInput) -> tuple[np.ndarray, np.ndarray]:
    n = plan.end_year - plan.start_year + 1
    return expected_returns(plan, n), np.full(n, plan.assumptions.inflation)


def _apply_years(plan: PlanInput, returns: np.ndarray, inflation: np.ndarray, start_year: int,
                 shocks: list[dict]) -> list[dict]:
    """Overwrite returns/inflation for consecutive plan years. Returns what was applied."""
    applied = []
    proxies = [c.proxy for c in plan.asset_classes]
    for k, shock in enumerate(shocks):
        t = start_year - plan.start_year + k
        if t < 0 or t >= returns.shape[1]:
            continue
        for c, proxy in enumerate(proxies):
            if shock.get(proxy) is not None:
                returns[0, t, c] = shock[proxy]
        if shock.get("inflation") is not None:
            inflation[t] = shock["inflation"]
        applied.append({"plan_year": plan.start_year + t, **{k2: v for k2, v in shock.items() if v is not None}})
    return applied


def _compare(plan: PlanInput, stressed_plan: PlanInput, returns: np.ndarray, inflation: np.ndarray,
             info: dict) -> dict:
    baseline = project(plan)
    stressed = project(stressed_plan, returns=returns, inflation=inflation)
    slim = ("year", "portfolio", "net_worth", "spending_total", "shortfall", "tax_total", "portfolio_return")
    return {
        **info,
        "baseline_summary": baseline["summary"],
        "stressed_summary": stressed["summary"],
        "years": stressed["years"],
        "price_index": stressed["price_index"],
        "baseline_price_index": baseline["price_index"],
        "baseline_rows": [{k: r[k] for k in slim} for r in baseline["rows"]],
        "stressed_rows": [{k: r[k] for k in slim} for r in stressed["rows"]],
        "meta": stressed["meta"],
        "warnings": stressed["warnings"],
    }


def run_historical(plan: PlanInput, key: str, start_year: int | None = None) -> dict:
    scenario = next((s for s in historical_data()["scenarios"] if s["key"] == key), None)
    if scenario is None:
        raise ValueError(f"Unknown historical scenario '{key}'")
    start = start_year or default_start_year(plan)
    returns, inflation = _base(plan)
    shocks = [{"equity": y["equity"] / 100, "bond": y["bond"] / 100, "cash": y["cash"] / 100,
               "inflation": y["inflation"] / 100, "historical_year": y["year"]} for y in scenario["years"]]
    applied = _apply_years(plan, returns, inflation, start, shocks)
    return _compare(plan, plan, returns, inflation, {
        "kind": "historical",
        "key": key,
        "name": scenario["name"],
        "plain": scenario["plain"],
        "start_year": start,
        "applied": applied,
        "data_note": historical_data()["note"],
        "data_as_of": historical_data()["as_of"],
        "label": "HISTORICAL DATA - a replay of what actually happened, not a prediction.",
    })


def run_custom(plan: PlanInput, stress: CustomStress) -> dict:
    stressed_plan = plan.model_copy(deep=True)
    if stress.extra_years_of_life:
        for m in stressed_plan.members:
            m.life_expectancy = min(m.life_expectancy + stress.extra_years_of_life, 120)
    start = stress.start_year or default_start_year(plan)
    returns, inflation = _base(stressed_plan)
    if stress.return_reduction:
        returns = returns - stress.return_reduction
    n_infl = stress.inflation_years or stress.duration_years
    shocks = []
    for k in range(max(stress.duration_years, n_infl if stress.inflation is not None else 0)):
        shock: dict = {}
        if k < stress.duration_years:
            shock.update({"equity": stress.equity_return, "bond": stress.bond_return, "cash": stress.cash_return})
        if stress.inflation is not None and k < n_infl:
            shock["inflation"] = stress.inflation
        shocks.append(shock)
    applied = _apply_years(stressed_plan, returns, inflation, start, shocks)
    return _compare(plan, stressed_plan, returns, inflation, {
        "kind": "custom",
        "name": stress.name,
        "start_year": start,
        "applied": applied,
        "parameters": stress.model_dump(),
        "label": "HYPOTHETICAL - a what-if you defined, not a prediction.",
    })


def run_sequence(plan: PlanInput, years: int = 5, severity: float = 1.0, start_year: int | None = None,
                 order: str = "bad_first") -> dict:
    """Sequence-of-returns test.

    For ``years`` years returns are mean - severity x volatility, and for the
    next ``years`` years mean + severity x volatility ("bad_first"), or the
    reverse ("good_first"). The arithmetic average return over the whole plan
    is unchanged; only the order differs.
    """
    if order not in ("bad_first", "good_first"):
        raise ValueError("order must be 'bad_first' or 'good_first'")
    start = start_year or default_start_year(plan)
    returns, inflation = _base(plan)
    sigma = np.array([c.volatility for c in plan.asset_classes])
    sign = -1.0 if order == "bad_first" else 1.0
    t0 = start - plan.start_year
    n = returns.shape[1]
    years = max(1, min(years, (n - t0) // 2))
    applied = []
    for k in range(2 * years):
        t = t0 + k
        if t < 0 or t >= n:
            continue
        direction = sign if k < years else -sign
        returns[0, t, :] = returns[0, t, :] + direction * severity * sigma
        applied.append({"plan_year": plan.start_year + t,
                        "shift": f"{'+' if direction > 0 else '-'}{severity:g} x volatility"})
    return _compare(plan, plan, returns, inflation, {
        "kind": "sequence",
        "name": "Bad years first" if order == "bad_first" else "Good years first",
        "plain": "Same average return over the plan; only the order of good and bad years changes.",
        "start_year": start,
        "applied": applied,
        "parameters": {"years": years, "severity": severity, "order": order},
        "label": "HYPOTHETICAL - illustrates why the order of returns matters, not a prediction.",
    })
