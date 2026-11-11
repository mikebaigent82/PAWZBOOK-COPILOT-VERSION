"""Plan input model for the calculation engine.

A ``PlanInput`` is a complete, self-contained description of a household's
finances and assumptions. The engine depends on nothing else (no database,
no clock, no network), so the same PlanInput always produces the same output.

All money amounts are annual and expressed in *start-year dollars* unless a
field says otherwise. Rates are decimals (0.025 means 2.5%).
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ENGINE_VERSION = "1.0.0"

FilingStatus = Literal["single", "mfj"]
TaxType = Literal["cash", "taxable", "traditional", "roth", "hsa"]
Proxy = Literal["equity", "bond", "cash"]
WithdrawalStrategy = Literal["taxable_first", "traditional_first", "roth_first", "proportional"]
Distribution = Literal["normal", "student_t", "laplace"]

JOINT = "joint"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SocialSecurity(_Model):
    """Social Security retirement benefit for one person."""

    monthly_benefit: float = Field(0, ge=0, description="Monthly benefit in start-year dollars.")
    basis: Literal["at_fra", "as_claimed"] = Field(
        "at_fra",
        description="'at_fra': the amount is the benefit at full retirement age (the PIA) and is "
        "adjusted for the claim age. 'as_claimed': the amount is already the actual benefit.",
    )
    claim_age: int = Field(67, ge=62, le=70)
    claim_months: int = Field(0, ge=0, le=11, description="Extra months beyond claim_age.")


class Member(_Model):
    id: str
    name: str
    birth_year: int = Field(ge=1900, le=2100)
    retirement_age: int = Field(65, ge=18, le=100)
    life_expectancy: int = Field(92, ge=50, le=120, description="Age through which the plan runs.")
    social_security: SocialSecurity = SocialSecurity()

    @property
    def retirement_year(self) -> int:
        return self.birth_year + self.retirement_age

    @property
    def death_year(self) -> int:
        """Last calendar year in which the member is alive."""
        return self.birth_year + self.life_expectancy


class AssetClass(_Model):
    key: str
    name: str
    expected_return: float = Field(description="Arithmetic mean annual nominal total return.")
    volatility: float = Field(ge=0, description="Annual standard deviation of returns.")
    income_yield: float = Field(0, ge=0, description="Part of the return paid out as interest/dividends.")
    qualified_ratio: float = Field(0, ge=0, le=1, description="Share of that income that is qualified dividends.")
    proxy: Proxy = "equity"


class Account(_Model):
    id: str
    name: str
    owner: str = Field(JOINT, description="Member id, or 'joint'.")
    tax_type: TaxType
    balance: float = Field(ge=0)
    cost_basis: float | None = Field(None, ge=0, description="Taxable accounts only. Defaults to the balance.")
    allocation: dict[str, float] = Field(description="Asset-class key -> weight. Must sum to 1.")
    annual_contribution: float = Field(0, ge=0)
    employer_match: float = Field(0, ge=0, description="Annual employer contribution in start-year dollars.")
    contribution_real_growth: float = Field(0, description="Growth of contributions above inflation.")
    annual_fee: float = Field(0, ge=0, le=0.05, description="Fees as a fraction of the balance per year.")

    @model_validator(mode="after")
    def _check(self) -> Account:
        total = sum(self.allocation.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"Account '{self.name}': allocation weights sum to {total:.4f}, expected 1.0")
        if any(w < 0 for w in self.allocation.values()):
            raise ValueError(f"Account '{self.name}': allocation weights cannot be negative")
        if self.tax_type in ("traditional", "roth", "hsa") and self.owner == JOINT:
            raise ValueError(f"Account '{self.name}': {self.tax_type} accounts need a single owner")
        return self


class Income(_Model):
    id: str
    name: str
    owner: str = JOINT
    kind: Literal["salary", "pension", "annuity", "rental", "business", "other"] = "salary"
    amount: float = Field(ge=0)
    start_year: int | None = None
    end_year: int | None = Field(None, description="Last year paid (inclusive).")
    growth_mode: Literal["inflation", "fixed", "none"] = "inflation"
    growth_rate: float = Field(0, description="'inflation': extra real growth. 'fixed': nominal growth.")
    tax_treatment: Literal["earned", "ordinary", "tax_free"] = "ordinary"
    survivor_pct: float = Field(0, ge=0, le=1, description="Share that continues after the owner dies.")


class Expense(_Model):
    id: str
    name: str
    amount: float = Field(ge=0)
    category: Literal["essential", "discretionary"] = "essential"
    kind: Literal["living", "healthcare", "housing", "one_time", "other"] = "living"
    start_year: int | None = None
    end_year: int | None = None
    inflation_mode: Literal["general", "healthcare", "none", "custom"] = "general"
    custom_rate: float = 0.0
    survivor_pct: float | None = Field(
        None, ge=0, le=2, description="Share that remains after the first death. None = plan default."
    )


class Liability(_Model):
    id: str
    name: str
    balance: float = Field(ge=0)
    interest_rate: float = Field(ge=0, le=1, description="Annual nominal rate.")
    monthly_payment: float = Field(ge=0)
    linked_asset_id: str | None = None


class IlliquidAsset(_Model):
    """Real estate or a privately held business."""

    id: str
    name: str
    kind: Literal["real_estate", "business"] = "real_estate"
    value: float = Field(ge=0)
    cost_basis: float = Field(0, ge=0)
    growth_rate: float = Field(0.03, description="Annual nominal growth of the value.")
    sale_year: int | None = None
    sale_cost_pct: float = Field(0.06, ge=0, le=1)
    primary_residence: bool = False


class RothConversion(_Model):
    mode: Literal["none", "fixed", "fill_bracket", "fill_magi"] = "none"
    amount: float = Field(0, ge=0, description="'fixed': annual amount. 'fill_magi': MAGI ceiling. Start-year dollars.")
    bracket_rate: float = Field(0.12, description="'fill_bracket': fill to the top of this bracket.")
    start_year: int | None = None
    end_year: int | None = None


class Guardrails(_Model):
    """Spending guardrails (Guyton-Klinger style, applied to discretionary spending)."""

    enabled: bool = False
    upper_band: float = Field(0.20, ge=0, description="Cut when withdrawal rate exceeds initial x (1+band).")
    lower_band: float = Field(0.20, ge=0, le=1, description="Raise when rate falls below initial x (1-band).")
    cut_pct: float = Field(0.10, ge=0, le=1)
    raise_pct: float = Field(0.10, ge=0, le=1)
    min_multiplier: float = Field(0.0, ge=0, le=1, description="Lowest share of discretionary spending kept.")
    max_multiplier: float = Field(1.5, ge=1)


class StateTax(_Model):
    state: str = "FL"
    rate: float = Field(0.0, ge=0, le=0.2, description="Effective rate applied to state taxable income.")
    taxes_social_security: bool = False
    exempts_retirement_income: bool = False


class Assumptions(_Model):
    inflation: float = 0.025
    healthcare_inflation: float = 0.05
    ss_cola: float | None = Field(None, description="None = same as inflation.")
    ss_reduction_pct: float = Field(0, ge=0, le=1, description="Benefit cut applied from ss_reduction_year.")
    ss_reduction_year: int | None = None
    spousal_benefits: bool = True
    withdrawal_strategy: WithdrawalStrategy = "taxable_first"
    roth_conversion: RothConversion = RothConversion()
    guardrails: Guardrails = Guardrails()
    state_tax: StateTax = StateTax()
    model_medicare_premiums: bool = True
    prior_magi: list[float] | None = Field(
        None, description="MAGI for the two years before the plan starts [y-2, y-1], for IRMAA."
    )
    survivor_expense_pct: float = Field(0.80, ge=0, le=2)
    heir_tax_rate: float = Field(0.22, ge=0, le=1, description="Tax rate heirs pay on inherited pre-tax money.")
    tax_rule_year: int | None = Field(None, description="Tax-rule version to use. None = latest <= start year.")


def default_asset_classes() -> list[AssetClass]:
    """Starting capital-market assumptions. They are assumptions, not forecasts,
    and every number can be overridden by the user."""
    return [
        AssetClass(key="us_stocks", name="US stocks", expected_return=0.070, volatility=0.160,
                   income_yield=0.015, qualified_ratio=0.95, proxy="equity"),
        AssetClass(key="intl_stocks", name="International stocks", expected_return=0.070, volatility=0.180,
                   income_yield=0.028, qualified_ratio=0.75, proxy="equity"),
        AssetClass(key="bonds", name="Bonds", expected_return=0.040, volatility=0.060,
                   income_yield=0.040, qualified_ratio=0.0, proxy="bond"),
        AssetClass(key="cash", name="Cash & savings", expected_return=0.030, volatility=0.010,
                   income_yield=0.030, qualified_ratio=0.0, proxy="cash"),
        AssetClass(key="real_estate", name="Real estate funds", expected_return=0.060, volatility=0.170,
                   income_yield=0.035, qualified_ratio=0.2, proxy="equity"),
        AssetClass(key="other", name="Other", expected_return=0.050, volatility=0.150,
                   income_yield=0.0, qualified_ratio=0.0, proxy="equity"),
    ]


def default_correlations() -> dict[str, dict[str, float]]:
    keys = ["us_stocks", "intl_stocks", "bonds", "cash", "real_estate", "other"]
    m = [
        [1.00, 0.80, 0.10, 0.00, 0.65, 0.50],
        [0.80, 1.00, 0.10, 0.00, 0.60, 0.50],
        [0.10, 0.10, 1.00, 0.20, 0.20, 0.10],
        [0.00, 0.00, 0.20, 1.00, 0.00, 0.00],
        [0.65, 0.60, 0.20, 0.00, 1.00, 0.40],
        [0.50, 0.50, 0.10, 0.00, 0.40, 1.00],
    ]
    return {a: {b: m[i][j] for j, b in enumerate(keys)} for i, a in enumerate(keys)}


class PlanInput(_Model):
    name: str = "My plan"
    start_year: int = Field(ge=2025, le=2100)
    filing_status: FilingStatus = "single"
    members: list[Member] = Field(min_length=1, max_length=2)
    accounts: list[Account] = []
    incomes: list[Income] = []
    expenses: list[Expense] = []
    liabilities: list[Liability] = []
    assets: list[IlliquidAsset] = []
    asset_classes: list[AssetClass] = Field(default_factory=default_asset_classes)
    correlations: dict[str, dict[str, float]] = Field(default_factory=default_correlations)
    assumptions: Assumptions = Assumptions()

    @model_validator(mode="after")
    def _check(self) -> PlanInput:
        ids = {m.id for m in self.members}
        if len(ids) != len(self.members):
            raise ValueError("Member ids must be unique")
        if self.filing_status == "mfj" and len(self.members) != 2:
            raise ValueError("Married filing jointly needs two household members")
        keys = [a.key for a in self.asset_classes]
        if len(set(keys)) != len(keys):
            raise ValueError("Asset-class keys must be unique")
        for acct in self.accounts:
            if acct.owner != JOINT and acct.owner not in ids:
                raise ValueError(f"Account '{acct.name}': unknown owner '{acct.owner}'")
            for k in acct.allocation:
                if k not in keys:
                    raise ValueError(f"Account '{acct.name}': unknown asset class '{k}'")
        for inc in self.incomes:
            if inc.owner != JOINT and inc.owner not in ids:
                raise ValueError(f"Income '{inc.name}': unknown owner '{inc.owner}'")
            if inc.tax_treatment == "earned" and inc.owner == JOINT:
                raise ValueError(f"Income '{inc.name}': earned income needs a single owner")
        for m in self.members:
            if m.death_year < self.start_year:
                raise ValueError(f"{m.name}: life expectancy ends before the plan starts")
        return self

    @property
    def end_year(self) -> int:
        return max(m.death_year for m in self.members)

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    def content_hash(self) -> str:
        """Stable fingerprint of the inputs, stored with every result."""
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()
