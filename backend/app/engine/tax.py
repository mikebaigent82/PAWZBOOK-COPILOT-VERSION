"""Federal, payroll and (simplified) state tax calculations.

Every function is vectorised: money arguments are NumPy arrays with one entry
per simulation path (a deterministic projection is simply one path). The
formulas follow the IRS tax-rate schedules (not the rounded tax tables).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .taxrules import YearTaxParams

Array = np.ndarray


def bracket_tax(income: Array, edges: Array, rates: Array) -> Array:
    """Progressive tax: each slice of income is taxed at its bracket's rate."""
    income = np.asarray(income, dtype=float)
    tax = np.zeros_like(income)
    n = len(edges)
    for i in range(n):
        lower = edges[i]
        width = (edges[i + 1] - lower) if i + 1 < n else np.inf
        tax += rates[i] * np.clip(income - lower, 0.0, width)
    return tax


def marginal_rate(income: Array, edges: Array, rates: Array) -> Array:
    idx = np.clip(np.searchsorted(edges, np.asarray(income, dtype=float), side="right") - 1, 0, len(rates) - 1)
    return rates[idx]


def taxable_social_security(other_income: Array, ss_benefits: Array, base1: float, base2: float) -> Array:
    """Taxable part of Social Security benefits (IRC 86 / IRS Pub. 915 worksheet).

    ``other_income`` is all other income counted in AGI (plus tax-exempt interest).
    Provisional income = other income + half of the benefits.
    """
    ss = np.asarray(ss_benefits, dtype=float)
    provisional = np.asarray(other_income, dtype=float) + 0.5 * ss
    tier1 = np.minimum(0.5 * ss, 0.5 * np.clip(provisional - base1, 0.0, None))
    tier1_cap = np.minimum(0.5 * ss, 0.5 * (base2 - base1))
    tier2 = np.minimum(0.85 * ss, 0.85 * np.clip(provisional - base2, 0.0, None) + tier1_cap)
    return np.where(provisional <= base2, tier1, tier2)


@dataclass
class FederalTax:
    agi: Array
    taxable_ss: Array
    deduction: Array
    taxable_income: Array
    ordinary_taxable_income: Array
    preferential_income: Array
    ordinary_tax: Array
    ltcg_tax: Array
    niit: Array
    total: Array
    marginal_rate: Array


def federal_income_tax(
    p: YearTaxParams,
    *,
    ordinary_income: Array,
    qualified_dividends: Array,
    long_term_gains: Array,
    ss_benefits: Array,
    net_investment_income: Array,
    n_age_65: int,
) -> FederalTax:
    """Federal income tax for one year.

    ordinary_income: wages (after pre-tax contributions), pensions, pre-tax
        account withdrawals, Roth conversions, interest, non-qualified dividends.
    qualified_dividends / long_term_gains: taxed at the 0/15/20% rates.
    net_investment_income: interest + dividends + gains, for the 3.8% NIIT.
    n_age_65: number of taxpayers aged 65 or older at year end.
    """
    ordinary_income = np.asarray(ordinary_income, dtype=float)
    pref_gross = np.asarray(qualified_dividends, dtype=float) + np.asarray(long_term_gains, dtype=float)
    other = ordinary_income + pref_gross
    taxable_ss = taxable_social_security(other, ss_benefits, p.ss_base1, p.ss_base2)
    agi = other + taxable_ss

    senior = n_age_65 * np.clip(
        p.senior_amount - p.senior_phaseout_rate * np.clip(agi - p.senior_phaseout_start, 0.0, None), 0.0, None
    )
    deduction = p.standard_deduction + n_age_65 * p.additional_65 + senior
    taxable_income = np.clip(agi - deduction, 0.0, None)

    pref = np.minimum(pref_gross, taxable_income)
    ordinary_ti = taxable_income - pref
    ordinary_tax = bracket_tax(ordinary_ti, p.bracket_edges, p.bracket_rates)

    # Capital gains "stack" on top of ordinary taxable income.
    at_0 = np.clip(p.ltcg_0_top - ordinary_ti, 0.0, pref)
    at_15 = np.clip(p.ltcg_15_top - np.maximum(ordinary_ti, p.ltcg_0_top), 0.0, pref - at_0)
    at_20 = pref - at_0 - at_15
    r0, r15, r20 = p.ltcg_rates
    ltcg_tax = r0 * at_0 + r15 * at_15 + r20 * at_20

    niit = p.niit_rate * np.minimum(
        np.clip(np.asarray(net_investment_income, dtype=float), 0.0, None),
        np.clip(agi - p.niit_threshold, 0.0, None),
    )
    total = ordinary_tax + ltcg_tax + niit
    return FederalTax(
        agi=agi,
        taxable_ss=taxable_ss,
        deduction=np.broadcast_to(deduction, agi.shape).copy(),
        taxable_income=taxable_income,
        ordinary_taxable_income=ordinary_ti,
        preferential_income=pref,
        ordinary_tax=ordinary_tax,
        ltcg_tax=ltcg_tax,
        niit=niit,
        total=total,
        marginal_rate=marginal_rate(ordinary_ti, p.bracket_edges, p.bracket_rates),
    )


def payroll_tax(p: YearTaxParams, wages_by_person: list[Array]) -> Array:
    """Employee share of Social Security and Medicare tax on wages.

    The Social Security wage base applies per person; the 0.9% additional
    Medicare tax applies to combined wages above the filing-status threshold.
    """
    if not wages_by_person:
        return np.zeros(1)
    total_wages = sum(np.asarray(w, dtype=float) for w in wages_by_person)
    tax = np.zeros_like(total_wages)
    for w in wages_by_person:
        w = np.asarray(w, dtype=float)
        tax = tax + p.ss_payroll_rate * np.minimum(w, p.ss_wage_base) + p.medicare_rate * w
    tax = tax + p.addl_medicare_rate * np.clip(total_wages - p.addl_medicare_threshold, 0.0, None)
    return tax


def state_income_tax(
    *,
    rate: float,
    agi: Array,
    taxable_ss: Array,
    retirement_income: Array,
    taxes_social_security: bool,
    exempts_retirement_income: bool,
) -> Array:
    """Simplified state tax: one effective rate on AGI less optional exclusions.

    This is a deliberate, documented simplification (see docs/CALCULATIONS.md).
    """
    if rate <= 0:
        return np.zeros_like(np.asarray(agi, dtype=float))
    base = np.asarray(agi, dtype=float).copy()
    if not taxes_social_security:
        base = base - taxable_ss
    if exempts_retirement_income:
        base = base - retirement_income
    return rate * np.clip(base, 0.0, None)


def irmaa_monthly(p: YearTaxParams, magi: Array) -> tuple[Array, Array]:
    """Monthly Medicare Part B and Part D surcharges per person for a given MAGI.

    IRMAA is a cliff: one dollar above a threshold triggers the whole surcharge.
    ``magi`` is the income from two years earlier.
    """
    magi = np.asarray(magi, dtype=float)
    # Tiers start above each threshold; the top tier starts at its threshold.
    tier = np.searchsorted(p.irmaa_thresholds[:-1], magi, side="left") + (magi >= p.irmaa_thresholds[-1])
    part_b = np.concatenate([[0.0], p.irmaa_part_b])[tier]
    part_d = np.concatenate([[0.0], p.irmaa_part_d])[tier]
    return part_b, part_d
