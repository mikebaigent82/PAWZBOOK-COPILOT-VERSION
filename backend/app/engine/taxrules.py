"""Versioned tax rules.

Each tax year lives in its own JSON file (``data/tax_rules_<year>.json``) with
its sources. For plan years after the newest published version, inflation-
indexed amounts are grown by the plan's inflation assumption; amounts that the
law does not index (Social Security taxation bases, NIIT thresholds, the
additional Medicare tax threshold, the senior deduction, the home-sale
exclusion) stay fixed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).parent / "data"


@dataclass(frozen=True)
class YearTaxParams:
    """Tax parameters for one plan year and filing status, already indexed."""

    year: int
    status: str
    rule_version: str
    index_factor: float
    bracket_edges: np.ndarray
    bracket_rates: np.ndarray
    standard_deduction: float
    additional_65: float
    senior_amount: float
    senior_phaseout_start: float
    senior_phaseout_rate: float
    ltcg_0_top: float
    ltcg_15_top: float
    ltcg_rates: tuple[float, float, float]
    niit_rate: float
    niit_threshold: float
    ss_base1: float
    ss_base2: float
    penalty_rate: float
    home_sale_exclusion: float
    ss_payroll_rate: float
    ss_wage_base: float
    medicare_rate: float
    addl_medicare_rate: float
    addl_medicare_threshold: float
    medicare_age: int
    part_b_monthly: float
    irmaa_thresholds: np.ndarray
    irmaa_part_b: np.ndarray
    irmaa_part_d: np.ndarray

    def bracket_top(self, rate: float) -> float:
        """Upper edge of the bracket taxed at ``rate`` (infinity for the top bracket)."""
        idx = int(np.argmin(np.abs(self.bracket_rates - rate)))
        if abs(float(self.bracket_rates[idx]) - rate) > 1e-9:
            raise ValueError(f"No {rate:.0%} bracket in rule version {self.rule_version}")
        if idx + 1 >= len(self.bracket_edges):
            return float("inf")
        return float(self.bracket_edges[idx + 1])


class TaxRuleSet:
    def __init__(self, raw: dict):
        self.raw = raw
        self.tax_year: int = raw["tax_year"]
        self.version: str = raw["version"]

    def params(self, year: int, status: str, index_factor: float = 1.0,
               medical_index_factor: float | None = None,
               irmaa_top_factor: float = 1.0) -> YearTaxParams:
        """Parameters for ``year``.

        ``index_factor``: cumulative inflation from this rule set's tax year to
        ``year`` (1.0 in the rule year itself). ``medical_index_factor``: the same
        for Medicare premiums. ``irmaa_top_factor``: cumulative inflation since the
        year before the top IRMAA tier starts being indexed (1.0 while frozen)."""
        if status not in ("single", "mfj"):
            raise ValueError(f"Unsupported filing status '{status}' (supported: single, mfj)")
        f = self.raw["federal"]
        p = self.raw["payroll"]
        m = self.raw["medicare"]
        k = float(index_factor)
        mk = float(medical_index_factor) if medical_index_factor is not None else k
        brackets = f["brackets"][status]
        sd = f["senior_deduction"]
        senior_active = sd["first_year"] <= year <= sd["last_year"]
        irmaa = np.array(m["irmaa"][status], dtype=float)
        thresholds = irmaa[:, 0] * k
        # By statute the top IRMAA tier is frozen, then indexed from a later year.
        thresholds[-1] = irmaa[-1, 0] * float(irmaa_top_factor)
        thresholds[-1] = max(thresholds[-1], thresholds[-2])
        return YearTaxParams(
            year=year,
            status=status,
            rule_version=self.version,
            index_factor=k,
            bracket_edges=np.array([b[0] for b in brackets], dtype=float) * k,
            bracket_rates=np.array([b[1] for b in brackets], dtype=float),
            standard_deduction=f["standard_deduction"][status] * k,
            additional_65=f["additional_std_deduction_65"][status] * k,
            senior_amount=float(sd["amount_per_person"]) if senior_active else 0.0,
            senior_phaseout_start=float(sd["phaseout_start"][status]),
            senior_phaseout_rate=float(sd["phaseout_rate"]),
            ltcg_0_top=f["ltcg_thresholds"][status][0] * k,
            ltcg_15_top=f["ltcg_thresholds"][status][1] * k,
            ltcg_rates=tuple(f["ltcg_rates"]),
            niit_rate=f["niit"]["rate"],
            niit_threshold=float(f["niit"]["threshold"][status]),
            ss_base1=float(f["ss_taxation"]["base1"][status]),
            ss_base2=float(f["ss_taxation"]["base2"][status]),
            penalty_rate=f["early_withdrawal_penalty_rate"],
            home_sale_exclusion=float(f["home_sale_exclusion"][status]),
            ss_payroll_rate=p["ss_rate"],
            ss_wage_base=p["ss_wage_base"] * k,
            medicare_rate=p["medicare_rate"],
            addl_medicare_rate=p["additional_medicare_rate"],
            addl_medicare_threshold=float(p["additional_medicare_threshold"][status]),
            medicare_age=m["eligibility_age"],
            part_b_monthly=m["part_b_standard_monthly"] * mk,
            irmaa_thresholds=thresholds,
            irmaa_part_b=irmaa[:, 1] * mk,
            irmaa_part_d=irmaa[:, 2] * mk,
        )


@cache
def available_years() -> tuple[int, ...]:
    return tuple(sorted(int(p.stem.rsplit("_", 1)[1]) for p in DATA_DIR.glob("tax_rules_*.json")))


@cache
def load_rules(tax_year: int) -> TaxRuleSet:
    path = DATA_DIR / f"tax_rules_{tax_year}.json"
    if not path.exists():
        raise FileNotFoundError(f"No tax rules for {tax_year}; available: {available_years()}")
    return TaxRuleSet(json.loads(path.read_text()))


def rules_for(start_year: int, requested: int | None = None) -> TaxRuleSet:
    """The rule version to use: an explicit request, else the newest version not
    later than the plan's start year (or the oldest one if the plan starts earlier)."""
    years = available_years()
    if requested is not None:
        return load_rules(requested)
    eligible = [y for y in years if y <= start_year]
    return load_rules(eligible[-1] if eligible else years[0])


@cache
def state_tax_data() -> dict:
    return json.loads((DATA_DIR / "state_tax.json").read_text())


def default_state_rate(state: str) -> float:
    data = state_tax_data()
    if state.upper() in data["no_wage_income_tax_states"]:
        return 0.0
    return float(data["default_effective_rate"])
