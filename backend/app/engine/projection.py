"""Deterministic year-by-year projection (one path using expected returns)."""
from __future__ import annotations

import numpy as np

from .models import ENGINE_VERSION, PlanInput
from .simulate import SERIES, SimResult, simulate

MONEY_DECIMALS = 2
RATE_SERIES = {"marginal_rate", "spending_multiplier", "withdrawal_rate", "portfolio_return"}


def _round(name: str, value: float) -> float:
    return round(float(value), 6 if name in RATE_SERIES else MONEY_DECIMALS)


def summarize(plan: PlanInput, res: SimResult, path: int = 0) -> dict:
    """Headline numbers for one path. Money is given in nominal dollars and in
    start-year ("today's") dollars, always labelled."""
    s = res.series
    idx = res.price_index
    shortfall = s["shortfall"][path]
    short_years = [int(y) for y, v in zip(res.years, shortfall) if v > 0.5]
    first_short = short_years[0] if short_years else None
    oldest = min(plan.members, key=lambda m: m.birth_year)
    youngest = max(plan.members, key=lambda m: m.birth_year)
    taxes = s["tax_total"][path]
    return {
        "funded": first_short is None,
        "first_shortfall_year": first_short,
        "first_shortfall_age": (first_short - youngest.birth_year) if first_short else None,
        "shortfall_years": len(short_years),
        "total_shortfall_real": round(float((shortfall / idx).sum()), 2),
        "plan_end_year": int(res.years[-1]),
        "plan_end_age_oldest": int(res.years[-1] - oldest.birth_year),
        "lifetime_taxes_nominal": round(float(taxes.sum()), 2),
        "lifetime_taxes_real": round(float((taxes / idx).sum()), 2),
        "lifetime_medicare_premiums_real": round(float((s["medicare_premiums"][path] / idx).sum()), 2),
        "lifetime_spending_real": round(float((s["spending_total"][path] / idx).sum()), 2),
        "total_roth_conversions_nominal": round(float(s["roth_conversion"][path].sum()), 2),
        "ending_portfolio_nominal": round(float(s["portfolio"][path, -1]), 2),
        "ending_portfolio_real": round(float(s["portfolio"][path, -1] / idx[-1]), 2),
        "ending_net_worth_nominal": round(float(s["net_worth"][path, -1]), 2),
        "ending_net_worth_real": round(float(s["net_worth"][path, -1] / idx[-1]), 2),
        "peak_portfolio_nominal": round(float(s["portfolio"][path].max()), 2),
        "max_marginal_rate": round(float(s["marginal_rate"][path].max()), 4),
    }


def meta(plan: PlanInput, res: SimResult) -> dict:
    return {
        "engine_version": ENGINE_VERSION,
        "plan_hash": res.plan_hash,
        "plan_name": plan.name,
        "start_year": plan.start_year,
        "end_year": plan.end_year,
        "tax_rule_versions": sorted({v for v in res.rule_versions if v}),
        "dollar_basis": "nominal (future dollars). Divide by price_index for start-year dollars.",
        "timing": "All cash flows occur at the start of each year; returns apply afterwards.",
        "inflation_assumption": plan.assumptions.inflation,
    }


def to_rows(plan: PlanInput, res: SimResult, path: int = 0) -> list[dict]:
    rows = []
    for t, year in enumerate(res.years):
        row: dict = {
            "year": int(year),
            "ages": {mid: ages[t] for mid, ages in res.ages.items()},
            "filing_status": res.filing_status[t],
            "price_index": round(float(res.price_index[t]), 6),
        }
        for name in SERIES:
            row[name] = _round(name, res.series[name][path, t])
        rows.append(row)
    return rows


def project(plan: PlanInput, returns: np.ndarray | None = None, inflation: np.ndarray | None = None) -> dict:
    """Run the deterministic projection and return a JSON-ready result."""
    res = simulate(plan, returns=returns, inflation=inflation)
    return {
        "meta": meta(plan, res),
        "summary": summarize(plan, res),
        "years": [int(y) for y in res.years],
        "price_index": [round(float(x), 6) for x in res.price_index],
        "rows": to_rows(plan, res),
        "accounts": [
            {
                "id": res.account_ids[i],
                "name": res.account_names[i],
                "tax_type": res.account_tax_types[i],
                "balances": [round(float(v), 2) for v in res.account_balances[0, :, i]],
            }
            for i in range(len(res.account_ids))
        ],
        "members": [{"id": m.id, "name": m.name, "birth_year": m.birth_year} for m in plan.members],
        "warnings": res.warnings,
    }
