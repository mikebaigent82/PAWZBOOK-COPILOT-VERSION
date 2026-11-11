"""Social Security retirement, spousal and survivor benefits (simplified).

Implemented rules (SSA):
* Full retirement age (FRA) by birth year.
* Early claiming: benefit reduced 5/9 of 1% per month for the first 36 months
  before FRA and 5/12 of 1% for each additional month.
* Delayed claiming: +2/3 of 1% per month after FRA, up to age 70.
* Spousal benefit: up to 50% of the worker's FRA benefit, reduced 25/36 of 1%
  per month for the first 36 months early and 5/12 of 1% beyond; no delayed
  credits. Paid as a top-up when it exceeds the spouse's own benefit.
* Survivor: the survivor keeps the larger of the two benefits.

Limitations: benefits are assumed to start in January of the claim year; the
earnings test, the family maximum, divorced-spouse rules and the survivor
early-claiming reduction are not modelled.
"""
from __future__ import annotations


def full_retirement_age_months(birth_year: int) -> int:
    """FRA in months. (SSA treats people born on January 1 as born the prior year.)"""
    if birth_year <= 1937:
        return 65 * 12
    if birth_year <= 1942:
        return 65 * 12 + 2 * (birth_year - 1937)
    if birth_year <= 1954:
        return 66 * 12
    if birth_year <= 1959:
        return 66 * 12 + 2 * (birth_year - 1954)
    return 67 * 12


def claim_factor(birth_year: int, claim_age_months: int) -> float:
    """Multiplier applied to the FRA benefit for the worker's own claim age."""
    fra = full_retirement_age_months(birth_year)
    claim = min(claim_age_months, 70 * 12)
    if claim >= fra:
        return 1.0 + (claim - fra) * (2.0 / 3.0) / 100.0
    early = fra - claim
    first = min(early, 36)
    rest = max(early - 36, 0)
    return 1.0 - first * (5.0 / 9.0) / 100.0 - rest * (5.0 / 12.0) / 100.0


def spousal_factor(birth_year: int, claim_age_months: int) -> float:
    """Multiplier applied to the 50% spousal benefit for the spouse's claim age."""
    fra = full_retirement_age_months(birth_year)
    if claim_age_months >= fra:
        return 1.0
    early = fra - claim_age_months
    first = min(early, 36)
    rest = max(early - 36, 0)
    return 1.0 - first * (25.0 / 36.0) / 100.0 - rest * (5.0 / 12.0) / 100.0
