"""Required minimum distributions (RMDs) from pre-tax retirement accounts."""
from __future__ import annotations

import json
from functools import cache

from .taxrules import DATA_DIR


@cache
def _divisors() -> dict[int, float]:
    raw = json.loads((DATA_DIR / "uniform_lifetime_table.json").read_text())
    return {int(k): float(v) for k, v in raw["divisors"].items()}


def rmd_start_age(birth_year: int) -> int:
    """Age at which RMDs begin (SECURE 2.0 Act): 72 if born 1950 or earlier,
    73 if born 1951-1959, 75 if born 1960 or later."""
    if birth_year <= 1950:
        return 72
    if birth_year <= 1959:
        return 73
    return 75


def uniform_lifetime_divisor(age: int) -> float:
    """Distribution period from the IRS Uniform Lifetime Table."""
    table = _divisors()
    if age < min(table):
        raise ValueError(f"No Uniform Lifetime divisor for age {age}")
    return table[min(age, max(table))]


def rmd_fraction(age: int, birth_year: int) -> float:
    """Share of the prior year-end balance that must be withdrawn this year.

    Limitation: uses the Uniform Lifetime Table for everyone (the Joint Life
    table for a spouse more than 10 years younger is not modelled).
    """
    if age < rmd_start_age(birth_year):
        return 0.0
    return 1.0 / uniform_lifetime_divisor(age)
