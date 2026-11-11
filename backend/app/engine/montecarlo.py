"""Monte Carlo simulation: many possible futures with random investment returns.

Reproducibility: returns are drawn from ``numpy.random.Generator(PCG64(seed))``
in a fixed order, so the same plan, seed, path count and distribution always
give identical results (for the same NumPy version, which is recorded).

Return model: each year's asset-class returns are r = mean + volatility * x,
where x has zero mean, unit variance and the plan's correlation matrix.
* normal:     x = L z                        (multivariate normal)
* student_t:  x = L z * sqrt((df-2)/chi2_df) (multivariate Student-t, fat tails)
* laplace:    x = L z * sqrt(Exp(1))         (symmetric multivariate Laplace)
with L the Cholesky factor of the correlation matrix. The scaling variable is
shared by all asset classes in a year, so extreme years hit everything together.
Returns are independent from year to year and floored at -100%.
"""
from __future__ import annotations

import numpy as np

from .models import ENGINE_VERSION, Distribution, PlanInput
from .projection import meta
from .simulate import SimResult, simulate

PERCENTILES = (10, 25, 50, 75, 90)
SUCCESS_TOLERANCE = 1.0  # dollars of unfunded spending tolerated in a year


def correlation_matrix(plan: PlanInput) -> np.ndarray:
    keys = [c.key for c in plan.asset_classes]
    n = len(keys)
    m = np.eye(n)
    for i, a in enumerate(keys):
        for j, b in enumerate(keys):
            if i == j:
                continue
            v = plan.correlations.get(a, {}).get(b)
            if v is None:
                v = plan.correlations.get(b, {}).get(a, 0.0)
            m[i, j] = v
    m = 0.5 * (m + m.T)
    if np.any(np.abs(m) > 1 + 1e-9):
        raise ValueError("Correlations must be between -1 and 1")
    if np.linalg.eigvalsh(m).min() < -1e-8:
        raise ValueError("The correlation matrix is not valid (not positive semi-definite)")
    return m


def generate_returns(plan: PlanInput, n_paths: int, n_years: int, seed: int,
                     distribution: Distribution = "normal", df: float = 5.0) -> np.ndarray:
    """Random annual returns with shape [paths, years, asset classes]."""
    if n_paths < 1:
        raise ValueError("n_paths must be at least 1")
    if distribution == "student_t" and df <= 2:
        raise ValueError("Student-t needs more than 2 degrees of freedom")
    rng = np.random.Generator(np.random.PCG64(seed))
    mu = np.array([c.expected_return for c in plan.asset_classes])
    sigma = np.array([c.volatility for c in plan.asset_classes])
    corr = correlation_matrix(plan)
    chol = np.linalg.cholesky(corr + 1e-12 * np.eye(len(mu)))
    z = rng.standard_normal((n_paths, n_years, len(mu)))
    x = z @ chol.T
    if distribution == "student_t":
        chi = rng.chisquare(df, size=(n_paths, n_years, 1))
        x = x * np.sqrt((df - 2.0) / chi)
    elif distribution == "laplace":
        e = rng.exponential(1.0, size=(n_paths, n_years, 1))
        x = x * np.sqrt(e)
    elif distribution != "normal":
        raise ValueError(f"Unknown distribution '{distribution}'")
    return np.clip(mu + sigma * x, -1.0, None)


def _pct(arr: np.ndarray) -> dict[str, list[float]]:
    q = np.percentile(arr, PERCENTILES, axis=0)
    return {f"p{p}": [round(float(v), 2) for v in q[i]] for i, p in enumerate(PERCENTILES)}


def summarize_paths(plan: PlanInput, res: SimResult) -> dict:
    s = res.series
    idx = res.price_index[None, :]
    P = res.n_paths
    short = s["shortfall"] > SUCCESS_TOLERANCE
    failed = short.any(axis=1)
    first_fail = np.where(failed, short.argmax(axis=1), -1)
    # Essentials are covered when the unfunded amount never exceeds planned discretionary spending.
    ess_fail = (s["shortfall"] > s["expenses_discretionary_planned"] * s["spending_multiplier"]
                + SUCCESS_TOLERANCE).any(axis=1)
    youngest = max(plan.members, key=lambda m: m.birth_year)
    fail_counts = np.bincount(first_fail[failed], minlength=len(res.years)) if failed.any() \
        else np.zeros(len(res.years), dtype=int)
    end_real = s["portfolio"][:, -1] / res.price_index[-1]
    mult = s["spending_multiplier"]
    hist_counts, hist_edges = np.histogram(end_real, bins=20)
    return {
        "n_paths": P,
        "success_probability": round(float(1.0 - failed.mean()), 4),
        "essential_success_probability": round(float(1.0 - ess_fail.mean()), 4),
        "failed_paths": int(failed.sum()),
        "median_failure_year": int(res.years[int(np.median(first_fail[failed]))]) if failed.any() else None,
        "median_failure_age": int(res.years[int(np.median(first_fail[failed]))] - youngest.birth_year)
        if failed.any() else None,
        "cumulative_failure_probability": [round(float(v), 4) for v in np.cumsum(fail_counts) / P],
        "portfolio_nominal": _pct(s["portfolio"]),
        "portfolio_real": _pct(s["portfolio"] / idx),
        "net_worth_real": _pct(s["net_worth"] / idx),
        "spending_real": _pct(s["spending_total"] / idx),
        "taxes_real": _pct(s["tax_total"] / idx),
        "ending_portfolio_real": {f"p{p}": round(float(np.percentile(end_real, p)), 2) for p in PERCENTILES},
        "ending_portfolio_real_histogram": {
            "edges": [round(float(e), 2) for e in hist_edges],
            "counts": [int(c) for c in hist_counts],
        },
        "lifetime_taxes_real": {
            f"p{p}": round(float(np.percentile((s["tax_total"] / idx).sum(axis=1), p)), 2) for p in PERCENTILES
        },
        "guardrails": {
            "enabled": plan.assumptions.guardrails.enabled,
            "paths_with_a_cut": round(float((mult.min(axis=1) < 1.0 - 1e-9).mean()), 4),
            "paths_with_a_raise": round(float((mult.max(axis=1) > 1.0 + 1e-9).mean()), 4),
            "average_multiplier_by_year": [round(float(v), 4) for v in mult.mean(axis=0)],
            "lowest_multiplier_p10": round(float(np.percentile(mult.min(axis=1), 10)), 4),
        },
    }


def run_monte_carlo(plan: PlanInput, n_paths: int = 1000, seed: int = 20260101,
                    distribution: Distribution = "normal", df: float = 5.0) -> dict:
    n_years = plan.end_year - plan.start_year + 1
    returns = generate_returns(plan, n_paths, n_years, seed, distribution, df)
    res = simulate(plan, returns=returns)
    out = summarize_paths(plan, res)
    m = meta(plan, res)
    m.update({
        "seed": seed,
        "n_paths": n_paths,
        "distribution": distribution,
        "degrees_of_freedom": df if distribution == "student_t" else None,
        "random_generator": "numpy PCG64",
        "numpy_version": np.__version__,
        "engine_version": ENGINE_VERSION,
        "success_definition": "A path succeeds when all planned spending (after any guardrail "
                              "adjustments) is paid in every year of the plan.",
    })
    return {
        "meta": m,
        "years": [int(y) for y in res.years],
        "price_index": [round(float(x), 6) for x in res.price_index],
        **out,
        "warnings": res.warnings,
    }
