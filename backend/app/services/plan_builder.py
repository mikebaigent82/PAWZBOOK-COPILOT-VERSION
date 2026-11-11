"""Turn the household's stored data into the engine's ``PlanInput``.

This is the only bridge between the database and the calculation engine.
Scenario overrides are applied here, on a copy: the stored (baseline) data is
never changed by a scenario.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..engine import models as em
from ..engine.lookthrough import CompositionPart, HoldingInput, asset_class_weights
from ..models import (
    Account,
    AssetClass,
    AssumptionSet,
    Business,
    Expense,
    Household,
    IncomeSource,
    Liability,
    Member,
    Pension,
    Plan,
    RealEstate,
)


class OneTimeExpense(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = "One-time expense"
    amount: float = Field(ge=0)
    year: int


class ExtraIncome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = "Extra income"
    amount: float = Field(ge=0)
    start_year: int | None = None
    end_year: int | None = None


class ScenarioOverrides(BaseModel):
    """What a what-if scenario may change. Member keys are member ids."""
    model_config = ConfigDict(extra="forbid")
    retirement_age: dict[str, int] = {}
    life_expectancy: dict[str, int] = {}
    ss_claim_age: dict[str, int] = {}
    expense_scale: float = Field(1.0, ge=0, le=5)
    discretionary_scale: float = Field(1.0, ge=0, le=5)
    one_time_expenses: list[OneTimeExpense] = []
    extra_incomes: list[ExtraIncome] = []
    return_shift: float = Field(0.0, ge=-0.2, le=0.2)
    assumptions: dict = {}

    def is_empty(self) -> bool:
        return self == ScenarioOverrides()


def _deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for k, v in patch.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def active_assumptions(db: Session, plan: Plan) -> AssumptionSet:
    row = db.scalars(select(AssumptionSet).where(AssumptionSet.plan_id == plan.id)
                     .order_by(AssumptionSet.version.desc())).first()
    if row is None:
        raise ValueError("The plan has no assumptions")
    return row


def holding_inputs(accounts: list[Account]) -> list[HoldingInput]:
    """Every investment position, for analytics. Accounts without holdings count
    as one position spread over their target allocation."""
    out: list[HoldingInput] = []
    for acct in accounts:
        if acct.holdings:
            for h in acct.holdings:
                s = h.security
                out.append(HoldingInput(
                    account_id=acct.id, account_name=acct.name, tax_type=acct.tax_type, symbol=s.symbol,
                    name=s.name, value=float(h.value or 0), asset_class=s.asset_class_key, is_fund=s.is_fund,
                    composition=[CompositionPart(**p) for p in (s.composition or [])],
                    composition_source=s.composition_source,
                    composition_as_of=s.composition_as_of.isoformat() if s.composition_as_of else None,
                ))
        elif float(acct.balance or 0) > 0:
            weights = {a.asset_class_key: a.weight for a in acct.allocations}
            if not weights:
                weights = {"cash": 1.0} if acct.tax_type == "cash" else {"us_stocks": 0.6, "bonds": 0.4}
            out.append(HoldingInput(
                account_id=acct.id, account_name=acct.name, tax_type=acct.tax_type, symbol=None,
                name=f"{acct.name} (whole account)", value=float(acct.balance), asset_class="other",
                is_fund=False,
                composition=[CompositionPart(kind="asset_class", key=k, weight=w) for k, w in weights.items()],
            ))
    return out


def build_plan_input(db: Session, household: Household, plan: Plan,
                     overrides: ScenarioOverrides | None = None,
                     name: str | None = None) -> tuple[em.PlanInput, list[str], int]:
    """Returns (plan input, notes about anything that was assumed, assumption version)."""
    ov = overrides or ScenarioOverrides()
    notes: list[str] = []
    hid = household.id

    def rows(model, order=None):
        q = select(model).where(model.household_id == hid).order_by(order if order is not None else model.created_at)
        return list(db.scalars(q).unique())

    db_members = sorted(rows(Member), key=lambda m: (m.relationship_kind != "self", m.created_at))[:2]
    if not db_members:
        raise ValueError("Add at least one person to the household first.")
    members: list[em.Member] = []
    for m in db_members:
        ss = m.ss_estimate
        claim_age = ov.ss_claim_age.get(m.id, ss.claim_age if ss else 67)
        members.append(em.Member(
            id=m.id, name=m.name, birth_year=m.birth_year,
            retirement_age=ov.retirement_age.get(m.id, m.retirement_age),
            life_expectancy=ov.life_expectancy.get(m.id, m.life_expectancy),
            social_security=em.SocialSecurity(
                monthly_benefit=float(ss.monthly_benefit) if ss else 0.0,
                basis=ss.basis if ss else "at_fra",
                claim_age=claim_age,
                claim_months=(ss.claim_months if ss and m.id not in ov.ss_claim_age else 0),
            ),
        ))
    by_id = {m.id: m for m in members}
    first = members[0]
    all_retired_year = max(m.retirement_year for m in members)

    filing = household.filing_status
    if filing == "mfj" and len(members) < 2:
        filing = "single"
        notes.append("Filing status was set to single because the household has one person.")

    classes = [em.AssetClass(key=c.key, name=c.name, expected_return=c.expected_return + ov.return_shift,
                             volatility=c.volatility, income_yield=c.income_yield,
                             qualified_ratio=c.qualified_ratio, proxy=c.proxy)
               for c in rows(AssetClass, AssetClass.sort_order)]
    class_keys = {c.key for c in classes}

    accounts: list[em.Account] = []
    for acct in rows(Account):
        owner = acct.member_id if acct.member_id in by_id else em.JOINT
        if acct.tax_type in ("traditional", "roth", "hsa") and owner == em.JOINT:
            owner = first.id
            notes.append(f"'{acct.name}' has no owner, so it was assigned to {first.name}.")
        positions = holding_inputs([acct])
        if acct.holdings:
            balance = sum(float(h.value or 0) for h in acct.holdings)
            weights = asset_class_weights(positions)
            bases = [h.cost_basis for h in acct.holdings]
            basis = float(sum(bases)) if all(b is not None for b in bases) and bases else acct.cost_basis
        else:
            balance = float(acct.balance or 0)
            weights = {a.asset_class_key: a.weight for a in acct.allocations}
            basis = acct.cost_basis
            if not weights:
                weights = {"cash": 1.0} if acct.tax_type == "cash" else {"us_stocks": 0.6, "bonds": 0.4}
                if acct.tax_type != "cash":
                    notes.append(f"'{acct.name}' has no investment mix set, so 60% stocks / 40% bonds was assumed.")
        weights = {k: w for k, w in weights.items() if w > 0}
        unknown = [k for k in weights if k not in class_keys]
        for k in unknown:
            weights["other" if "other" in class_keys else classes[0].key] = \
                weights.get("other" if "other" in class_keys else classes[0].key, 0) + weights.pop(k)
        total = sum(weights.values()) or 1.0
        weights = {k: w / total for k, w in weights.items()} or {classes[0].key: 1.0}
        if basis is not None and acct.tax_type in ("cash", "taxable"):
            basis = min(float(basis), balance) if balance > 0 else 0.0
        accounts.append(em.Account(
            id=acct.id, name=acct.name, owner=owner, tax_type=acct.tax_type, balance=balance,
            cost_basis=basis if acct.tax_type in ("cash", "taxable") else None, allocation=weights,
            annual_contribution=float(acct.annual_contribution or 0), employer_match=float(acct.employer_match or 0),
            contribution_real_growth=acct.contribution_real_growth or 0, annual_fee=acct.annual_fee or 0,
        ))

    incomes: list[em.Income] = []
    for inc in rows(IncomeSource):
        owner = inc.member_id if inc.member_id in by_id else em.JOINT
        treatment = inc.tax_treatment
        if treatment == "earned" and owner == em.JOINT:
            owner = first.id
        end_year = inc.end_year
        if inc.ends_at_retirement:
            retire = by_id[owner].retirement_year if owner != em.JOINT else all_retired_year
            end_year = retire - 1 if end_year is None else min(end_year, retire - 1)
        incomes.append(em.Income(
            id=inc.id, name=inc.name, owner=owner, kind=inc.kind, amount=float(inc.amount),
            start_year=inc.start_year, end_year=end_year, growth_mode=inc.growth_mode,
            growth_rate=inc.growth_rate or 0, tax_treatment=treatment, survivor_pct=inc.survivor_pct or 0,
        ))
    for p in rows(Pension):
        if p.member_id not in by_id:
            continue
        owner_m = by_id[p.member_id]
        incomes.append(em.Income(
            id=p.id, name=p.name, owner=p.member_id, kind="pension", amount=float(p.annual_amount),
            start_year=owner_m.birth_year + p.start_age, growth_mode="inflation" if p.has_cola else "none",
            tax_treatment="ordinary", survivor_pct=p.survivor_pct or 0,
        ))
    for x in ov.extra_incomes:
        incomes.append(em.Income(id=f"extra_{len(incomes)}", name=x.name, owner=em.JOINT, kind="other",
                                 amount=x.amount, start_year=x.start_year, end_year=x.end_year))

    expenses: list[em.Expense] = []
    for e in rows(Expense):
        start, end = e.start_year, e.end_year
        if e.starts_at_retirement:
            start = all_retired_year if start is None else max(start, all_retired_year)
        if e.ends_at_retirement:
            end = all_retired_year - 1 if end is None else min(end, all_retired_year - 1)
        scale = ov.expense_scale * (ov.discretionary_scale if e.category == "discretionary" else 1.0)
        if e.kind == "one_time":
            scale = 1.0
        expenses.append(em.Expense(
            id=e.id, name=e.name, amount=float(e.amount) * scale, category=e.category, kind=e.kind,
            start_year=start, end_year=end, inflation_mode=e.inflation_mode, custom_rate=e.custom_rate or 0,
            survivor_pct=e.survivor_pct,
        ))
    for x in ov.one_time_expenses:
        expenses.append(em.Expense(id=f"once_{len(expenses)}", name=x.name, amount=x.amount, kind="one_time",
                                   category="essential", start_year=x.year, end_year=x.year))

    assets: list[em.IlliquidAsset] = []
    for r in rows(RealEstate):
        assets.append(em.IlliquidAsset(
            id=r.id, name=r.name, kind="real_estate", value=float(r.value), cost_basis=float(r.cost_basis or 0),
            growth_rate=r.growth_rate, sale_year=r.sale_year, sale_cost_pct=r.sale_cost_pct,
            primary_residence=r.primary_residence))
    for b in rows(Business):
        assets.append(em.IlliquidAsset(
            id=b.id, name=b.name, kind="business", value=float(b.value), cost_basis=float(b.cost_basis or 0),
            growth_rate=b.growth_rate, sale_year=b.sale_year, sale_cost_pct=b.sale_cost_pct))
        if float(b.annual_income or 0) > 0:
            incomes.append(em.Income(
                id=f"biz_{b.id}", name=f"{b.name} income", owner=b.member_id if b.member_id in by_id else em.JOINT,
                kind="business", amount=float(b.annual_income),
                end_year=(b.sale_year - 1) if b.sale_year else None, tax_treatment="ordinary"))
    asset_ids = {a.id for a in assets}
    liabilities = [em.Liability(id=lb.id, name=lb.name, balance=float(lb.balance), interest_rate=lb.interest_rate,
                                monthly_payment=float(lb.monthly_payment),
                                linked_asset_id=lb.real_estate_id if lb.real_estate_id in asset_ids else None)
                   for lb in rows(Liability)]

    aset = active_assumptions(db, plan)
    payload = _deep_merge(aset.payload, ov.assumptions)
    assumptions = em.Assumptions.model_validate(payload)
    assumptions.state_tax.state = household.state

    plan_input = em.PlanInput(
        name=name or plan.name, start_year=plan.start_year, filing_status=filing, members=members,
        accounts=accounts, incomes=incomes, expenses=expenses, liabilities=liabilities, assets=assets,
        asset_classes=classes, correlations=aset.correlations or em.default_correlations(),
        assumptions=assumptions,
    )
    return plan_input, notes, aset.version
