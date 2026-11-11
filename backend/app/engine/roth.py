"""Roth conversion and withdrawal-strategy comparison.

The optimizer does not guess: it runs the full deterministic projection for a
set of clearly defined candidate strategies and compares them on three
objectives. All candidates and their numbers are returned so the choice is
fully traceable.

Objectives (all in start-year dollars):
* lifetime_cost:      lifetime taxes + Medicare premiums (lower is better)
* after_tax_wealth:   ending portfolio with pre-tax balances reduced by the
                      household's own final-year tax rates (higher is better)
* beneficiary_value:  ending portfolio as heirs would receive it: pre-tax and
                      HSA balances reduced by ``heir_tax_rate``; Roth, cash and
                      taxable accounts at full value (stepped-up basis)
"""
from __future__ import annotations

from .models import PlanInput, RothConversion
from .projection import summarize
from .rmd import rmd_start_age
from .simulate import simulate
from .taxrules import rules_for

DEFAULT_WEIGHTS = {"lifetime_cost": 1.0, "after_tax_wealth": 1.0, "beneficiary_value": 1.0}


def _metrics(plan: PlanInput) -> tuple[dict, list[float]]:
    res = simulate(plan)
    s = res.series
    idx = res.price_index
    summary = summarize(plan, res)
    end = idx[-1]
    trad = float(s["balance_traditional"][0, -1])
    roth = float(s["balance_roth"][0, -1])
    hsa = float(s["balance_hsa"][0, -1])
    liquid = float(s["balance_cash"][0, -1] + s["balance_taxable"][0, -1])
    own_rate = min(float(s["marginal_rate"][0, -1]) + plan.assumptions.state_tax.rate, 1.0)
    heir = plan.assumptions.heir_tax_rate
    metrics = {
        "lifetime_taxes_real": summary["lifetime_taxes_real"],
        "lifetime_medicare_premiums_real": summary["lifetime_medicare_premiums_real"],
        "lifetime_cost": round(summary["lifetime_taxes_real"] + summary["lifetime_medicare_premiums_real"], 2),
        "after_tax_wealth": round((liquid + roth + hsa + trad * (1 - own_rate)) / end, 2),
        "beneficiary_value": round((liquid + roth + (trad + hsa) * (1 - heir)) / end, 2),
        "ending_portfolio_real": summary["ending_portfolio_real"],
        "total_converted_nominal": summary["total_roth_conversions_nominal"],
        "max_marginal_rate": summary["max_marginal_rate"],
        "total_shortfall_real": summary["total_shortfall_real"],
        "funded": summary["funded"],
    }
    return metrics, [round(float(v), 2) for v in s["roth_conversion"][0]]


def conversion_window(plan: PlanInput) -> tuple[int, int] | None:
    """The 'gap years': from the retirement of the first owner of pre-tax money
    until the year before required distributions begin."""
    owners = {a.owner for a in plan.accounts if a.tax_type == "traditional" and a.balance > 0}
    members = [m for m in plan.members if m.id in owners]
    if not members:
        return None
    start = max(plan.start_year, min(m.retirement_year for m in members))
    end = min(m.birth_year + rmd_start_age(m.birth_year) for m in members) - 1
    end = min(end, plan.end_year)
    if end < start:
        return None
    return start, end


def _candidates(plan: PlanInput) -> list[tuple[str, str, RothConversion]]:
    out = [("none", "No Roth conversions", RothConversion(mode="none"))]
    window = conversion_window(plan)
    if window is None:
        return out
    gap_start, gap_end = window
    windows = [("gap", f"{gap_start}-{gap_end}", gap_start, gap_end)]
    if plan.start_year < gap_start:
        windows.append(("now", f"{plan.start_year}-{gap_end}", plan.start_year, gap_end))
    rules = rules_for(plan.start_year, plan.assumptions.tax_rule_year)
    rates = [b[1] for b in rules.raw["federal"]["brackets"][plan.filing_status]]
    for wkey, wlabel, ws, we in windows:
        for rate in rates:
            if rate > 0.32 + 1e-9:
                continue
            out.append((
                f"fill_{int(round(rate * 100))}_{wkey}",
                f"Fill the {rate:.0%} tax bracket each year, {wlabel}",
                RothConversion(mode="fill_bracket", bracket_rate=rate, start_year=ws, end_year=we),
            ))
        irmaa_first = rules.raw["medicare"]["irmaa"][plan.filing_status][0][0]
        out.append((
            f"irmaa_{wkey}",
            f"Convert up to the first Medicare surcharge threshold each year, {wlabel}",
            RothConversion(mode="fill_magi", amount=float(irmaa_first), start_year=ws, end_year=we),
        ))
    return out


def _score(rows: list[dict], weights: dict[str, float]) -> None:
    """Add a 0-100 score to each row: weighted average of min-max normalised objectives."""
    total_w = sum(max(w, 0.0) for w in weights.values()) or 1.0
    spans = {}
    for key in ("lifetime_cost", "after_tax_wealth", "beneficiary_value"):
        vals = [r["metrics"][key] for r in rows]
        spans[key] = (min(vals), max(vals))
    for r in rows:
        score = 0.0
        for key, (lo, hi) in spans.items():
            norm = 0.5 if hi - lo < 1e-9 else (r["metrics"][key] - lo) / (hi - lo)
            if key == "lifetime_cost":
                norm = 1.0 - norm
            score += max(weights.get(key, 0.0), 0.0) * norm
        r["score"] = round(100.0 * score / total_w, 2)
    for r in rows:
        m = r["metrics"]
        r["pareto_efficient"] = not any(
            o is not r
            and o["metrics"]["lifetime_cost"] <= m["lifetime_cost"]
            and o["metrics"]["after_tax_wealth"] >= m["after_tax_wealth"]
            and o["metrics"]["beneficiary_value"] >= m["beneficiary_value"]
            and (o["metrics"]["lifetime_cost"] < m["lifetime_cost"]
                 or o["metrics"]["after_tax_wealth"] > m["after_tax_wealth"]
                 or o["metrics"]["beneficiary_value"] > m["beneficiary_value"])
            for o in rows
        )


def optimize_roth(plan: PlanInput, weights: dict[str, float] | None = None) -> dict:
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    rows = []
    for key, label, conv in _candidates(plan):
        candidate = plan.model_copy(deep=True)
        candidate.assumptions.roth_conversion = conv
        metrics, conversions = _metrics(candidate)
        rows.append({"key": key, "label": label, "conversion": conv.model_dump(), "metrics": metrics,
                     "conversions_by_year": conversions})
    _score(rows, weights)
    baseline = rows[0]
    # A strategy that causes (or worsens) a shortfall is never recommended.
    eligible = [r for r in rows
                if r["metrics"]["total_shortfall_real"] <= baseline["metrics"]["total_shortfall_real"] + 1.0]
    best = max(eligible, key=lambda r: (r["score"], r["key"] == "none"))
    for r in rows:
        r["vs_baseline"] = {
            k: round(r["metrics"][k] - baseline["metrics"][k], 2)
            for k in ("lifetime_cost", "after_tax_wealth", "beneficiary_value")
        }
    return {
        "weights": weights,
        "years": list(range(plan.start_year, plan.end_year + 1)),
        "window": conversion_window(plan),
        "recommended_key": best["key"],
        "candidates": sorted(rows, key=lambda r: -r["score"]),
        "method": "Each candidate is a full deterministic projection using expected returns. "
                  "Scores are a weighted average of the three objectives, each scaled 0-1 across candidates.",
        "limitations": [
            "Based on expected (average) returns, not on Monte Carlo outcomes.",
            "Future tax law is assumed to stay as in the current rule version, indexed for inflation.",
            "The 5-year rule for withdrawing converted amounts before age 59 1/2 is not modelled.",
        ],
    }


STRATEGY_LABELS = {
    "taxable_first": "Savings and taxable accounts first, then pre-tax, Roth last",
    "traditional_first": "Pre-tax accounts first, then taxable, Roth last",
    "roth_first": "Roth first, then taxable, pre-tax last",
    "proportional": "A proportional slice from every account",
}


def compare_withdrawal_strategies(plan: PlanInput, weights: dict[str, float] | None = None) -> dict:
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    rows = []
    for key, label in STRATEGY_LABELS.items():
        candidate = plan.model_copy(deep=True)
        candidate.assumptions.withdrawal_strategy = key  # type: ignore[assignment]
        metrics, _ = _metrics(candidate)
        rows.append({"key": key, "label": label, "metrics": metrics,
                     "current": key == plan.assumptions.withdrawal_strategy})
    _score(rows, weights)
    least_short = min(r["metrics"]["total_shortfall_real"] for r in rows)
    eligible = [r for r in rows if r["metrics"]["total_shortfall_real"] <= least_short + 1.0]
    best = max(eligible, key=lambda r: r["score"])
    return {"weights": weights, "recommended_key": best["key"],
            "candidates": sorted(rows, key=lambda r: -r["score"])}
