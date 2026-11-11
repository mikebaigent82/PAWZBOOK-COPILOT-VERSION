"""Household data: people, accounts, holdings, income, expenses, property, debts."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select

from ..engine.lookthrough import analyze
from ..engine.taxrules import default_state_rate, state_tax_data
from ..models import (
    Account,
    Allocation,
    AssetClass,
    Business,
    Expense,
    Holding,
    Household,
    IncomeSource,
    Liability,
    Member,
    Pension,
    RealEstate,
    Security,
    SSEstimate,
    Transaction,
)
from ..services import csv_import
from ..services.assumptions import save_assumptions
from ..services.plan_builder import holding_inputs
from ..services.setup import ALLOCATION_PRESETS, current_year, load_sample_data
from .deps import Ctx, get_ctx, get_writer

router = APIRouter(tags=["data"])
TaxType = Literal["cash", "taxable", "traditional", "roth", "hsa"]


class In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def row_dict(row, exclude: tuple[str, ...] = ("household_id",)) -> dict:
    out = {}
    for col in sa_inspect(row).mapper.column_attrs:
        if col.key in exclude:
            continue
        v = getattr(row, col.key)
        out[col.key] = v.isoformat() if isinstance(v, (date, datetime)) else v
    return out


def check_member(ctx: Ctx, member_id: str | None) -> None:
    if member_id is not None:
        ctx.owned(Member, member_id)


# ----------------------------------------------------------------------------- household & people


class HouseholdIn(In):
    name: str | None = Field(None, min_length=1, max_length=120)
    filing_status: Literal["single", "mfj"] | None = None
    state: str | None = Field(None, min_length=2, max_length=2)
    onboarding_complete: bool | None = None


@router.get("/household")
def get_household(ctx: Ctx = Depends(get_ctx)):
    members = list(ctx.db.scalars(select(Member).where(Member.household_id == ctx.hid)).unique())
    return {**row_dict(ctx.household, exclude=("owner_user_id",)), "role": ctx.role,
            "member_count": len(members), "current_year": current_year(),
            "states": state_tax_data()["states"],
            "no_income_tax_states": state_tax_data()["no_wage_income_tax_states"]}


@router.patch("/household")
def update_household(body: HouseholdIn, ctx: Ctx = Depends(get_writer)):
    h: Household = ctx.household
    data = body.model_dump(exclude_unset=True)
    if "state" in data:
        state = data["state"].upper()
        if state not in state_tax_data()["states"]:
            raise HTTPException(422, "Unknown state.")
        if state != h.state:
            h.state = state
            save_assumptions(ctx, {"state_tax": {"state": state, "rate": default_state_rate(state)}},
                             note=f"State changed to {state}")
    if data.get("filing_status") == "mfj":
        n = len(list(ctx.db.scalars(select(Member).where(Member.household_id == ctx.hid)).unique()))
        if n < 2:
            raise HTTPException(422, "Add your spouse first, then choose married filing jointly.")
    for k in ("name", "filing_status", "onboarding_complete"):
        if k in data and data[k] is not None:
            setattr(h, k, data[k])
    ctx.log("household.update", "household", h.id, {"fields": sorted(data)})
    return get_household(ctx)


class MemberIn(In):
    name: str = Field(min_length=1, max_length=120)
    relationship_kind: Literal["self", "spouse"] = "self"
    birth_year: int = Field(ge=1900, le=2100)
    retirement_age: int = Field(65, ge=18, le=100)
    life_expectancy: int = Field(92, ge=50, le=120)
    ss_monthly_benefit: float = Field(0, ge=0, le=20000)
    ss_basis: Literal["at_fra", "as_claimed"] = "at_fra"
    ss_claim_age: int = Field(67, ge=62, le=70)

    @model_validator(mode="after")
    def _check(self):
        if self.life_expectancy <= current_year() - self.birth_year:
            raise ValueError("The plan-to age must be older than the person is today.")
        return self


def member_out(m: Member) -> dict:
    ss = m.ss_estimate
    return {**row_dict(m), "age": current_year() - m.birth_year,
            "ss_monthly_benefit": float(ss.monthly_benefit) if ss else 0.0,
            "ss_basis": ss.basis if ss else "at_fra", "ss_claim_age": ss.claim_age if ss else 67}


def _apply_member(ctx: Ctx, m: Member, body: MemberIn) -> None:
    for k in ("name", "relationship_kind", "birth_year", "retirement_age", "life_expectancy"):
        setattr(m, k, getattr(body, k))
    ctx.db.flush()
    if m.ss_estimate is None:
        m.ss_estimate = SSEstimate(household_id=ctx.hid, member_id=m.id)
    m.ss_estimate.monthly_benefit = body.ss_monthly_benefit
    m.ss_estimate.basis = body.ss_basis
    m.ss_estimate.claim_age = body.ss_claim_age
    m.ss_estimate.as_of = date.today()
    m.ss_estimate.source = "Entered by user"


@router.get("/members")
def list_members(ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.scalars(select(Member).where(Member.household_id == ctx.hid).order_by(Member.created_at)).unique()
    return [member_out(m) for m in sorted(rows, key=lambda m: m.relationship_kind != "self")]


@router.post("/members", status_code=201)
def create_member(body: MemberIn, ctx: Ctx = Depends(get_writer)):
    n = len(list(ctx.db.scalars(select(Member).where(Member.household_id == ctx.hid)).unique()))
    if n >= 2:
        raise HTTPException(422, "A household can have up to two people (you and a spouse or partner).")
    m = Member(household_id=ctx.hid, name=body.name, birth_year=body.birth_year)
    ctx.db.add(m)
    _apply_member(ctx, m, body)
    ctx.db.flush()
    ctx.log("member.create", "member", m.id)
    return member_out(m)


@router.put("/members/{member_id}")
def update_member(member_id: str, body: MemberIn, ctx: Ctx = Depends(get_writer)):
    m = ctx.owned(Member, member_id)
    _apply_member(ctx, m, body)
    ctx.log("member.update", "member", m.id)
    return member_out(m)


@router.delete("/members/{member_id}", status_code=204)
def delete_member(member_id: str, ctx: Ctx = Depends(get_writer)):
    m = ctx.owned(Member, member_id)
    ctx.db.delete(m)
    ctx.db.flush()
    remaining = len(list(ctx.db.scalars(select(Member).where(Member.household_id == ctx.hid)).unique()))
    if remaining < 2 and ctx.household.filing_status == "mfj":
        ctx.household.filing_status = "single"
    ctx.log("member.delete", "member", member_id)
    return Response(status_code=204)


# ----------------------------------------------------------------------------- accounts & holdings


class AccountIn(In):
    name: str = Field(min_length=1, max_length=120)
    tax_type: TaxType
    member_id: str | None = None
    institution: str | None = Field(None, max_length=120)
    balance: float = Field(0, ge=0)
    cost_basis: float | None = Field(None, ge=0)
    annual_contribution: float = Field(0, ge=0)
    employer_match: float = Field(0, ge=0)
    annual_fee: float = Field(0, ge=0, le=0.05)
    allocation_preset: Literal["cash", "conservative", "balanced", "growth", "aggressive"] | None = None
    allocation: dict[str, float] | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.allocation is not None:
            total = sum(self.allocation.values())
            if any(w < 0 for w in self.allocation.values()) or abs(total - 1.0) > 0.005:
                raise ValueError("The investment mix must add up to 100%.")
        return self


def account_out(a: Account) -> dict:
    holdings = [{**row_dict(h), "symbol": h.security.symbol, "name": h.security.name,
                 "asset_class_key": h.security.asset_class_key, "is_fund": h.security.is_fund}
                for h in a.holdings]
    value = sum(float(h.value or 0) for h in a.holdings) if a.holdings else float(a.balance or 0)
    alloc = {x.asset_class_key: x.weight for x in a.allocations}
    preset = next((k for k, v in ALLOCATION_PRESETS.items()
                   if set(v) == set(alloc) and all(abs(v[x] - alloc[x]) < 1e-6 for x in v)), None)
    return {**row_dict(a), "value": round(value, 2), "allocation": alloc, "allocation_preset": preset,
            "holdings": holdings, "has_holdings": bool(holdings)}


def _apply_account(ctx: Ctx, a: Account, body: AccountIn) -> None:
    check_member(ctx, body.member_id)
    if body.tax_type in ("traditional", "roth", "hsa") and body.member_id is None:
        raise HTTPException(422, "Retirement and health accounts belong to one person. Please choose the owner.")
    for k in ("name", "tax_type", "member_id", "institution", "balance", "cost_basis", "annual_contribution",
              "employer_match", "annual_fee"):
        setattr(a, k, getattr(body, k))
    a.balance_as_of = date.today()
    ctx.db.flush()
    weights = body.allocation
    if weights is None and body.allocation_preset:
        weights = ALLOCATION_PRESETS[body.allocation_preset]
    if weights is None and not a.allocations:
        weights = ALLOCATION_PRESETS["cash" if body.tax_type == "cash" else "balanced"]
    if weights is not None:
        keys = set(ctx.db.scalars(select(AssetClass.key).where(AssetClass.household_id == ctx.hid)))
        if not set(weights) <= keys:
            raise HTTPException(422, "Unknown investment type in the mix.")
        for old in list(a.allocations):
            ctx.db.delete(old)
        ctx.db.flush()
        for key, w in weights.items():
            if w > 0:
                a.allocations.append(Allocation(household_id=ctx.hid, account_id=a.id, asset_class_key=key, weight=w))
    ctx.db.flush()


@router.get("/accounts")
def list_accounts(ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.scalars(select(Account).where(Account.household_id == ctx.hid).order_by(Account.created_at)).unique()
    return [account_out(a) for a in rows]


@router.post("/accounts", status_code=201)
def create_account(body: AccountIn, ctx: Ctx = Depends(get_writer)):
    a = Account(household_id=ctx.hid, name=body.name, tax_type=body.tax_type)
    ctx.db.add(a)
    ctx.db.flush()
    _apply_account(ctx, a, body)
    ctx.log("account.create", "account", a.id)
    ctx.db.refresh(a)
    return account_out(a)


@router.put("/accounts/{account_id}")
def update_account(account_id: str, body: AccountIn, ctx: Ctx = Depends(get_writer)):
    a = ctx.owned(Account, account_id)
    _apply_account(ctx, a, body)
    ctx.log("account.update", "account", a.id)
    ctx.db.refresh(a)
    return account_out(a)


@router.delete("/accounts/{account_id}", status_code=204)
def delete_account(account_id: str, ctx: Ctx = Depends(get_writer)):
    ctx.db.delete(ctx.owned(Account, account_id))
    ctx.log("account.delete", "account", account_id)
    return Response(status_code=204)


class CompositionIn(In):
    kind: Literal["asset_class", "security", "sector"]
    key: str = Field(min_length=1, max_length=60)
    name: str | None = Field(None, max_length=120)
    weight: float = Field(ge=0, le=1)


class HoldingIn(In):
    symbol: str = Field(min_length=1, max_length=20)
    name: str | None = Field(None, max_length=160)
    asset_class_key: str = "other"
    is_fund: bool = False
    value: float = Field(ge=0)
    cost_basis: float | None = Field(None, ge=0)
    quantity: float | None = Field(None, ge=0)
    composition: list[CompositionIn] | None = None
    composition_source: str | None = Field(None, max_length=160)


@router.post("/accounts/{account_id}/holdings", status_code=201)
def add_holding(account_id: str, body: HoldingIn, ctx: Ctx = Depends(get_writer)):
    a = ctx.owned(Account, account_id)
    keys = set(ctx.db.scalars(select(AssetClass.key).where(AssetClass.household_id == ctx.hid)))
    if body.asset_class_key not in keys:
        raise HTTPException(422, "Unknown investment type.")
    symbol = body.symbol.upper()
    sec = ctx.db.scalar(select(Security).where(Security.household_id == ctx.hid, Security.symbol == symbol))
    if sec is None:
        sec = csv_import._security(ctx.db, ctx.hid, symbol, body.name or symbol, body.asset_class_key)
        if not sec.composition:
            sec.is_fund = body.is_fund
    if body.name:
        sec.name = body.name
    if body.composition is not None:
        for kind in ("asset_class", "security", "sector"):
            if sum(p.weight for p in body.composition if p.kind == kind) > 1.0001:
                raise HTTPException(422, f"The {kind.replace('_', ' ')} weights add up to more than 100%.")
        sec.composition = [p.model_dump() for p in body.composition]
        sec.composition_source = body.composition_source or "Entered by user"
        sec.composition_as_of = date.today()
        sec.is_fund = True
    h = Holding(household_id=ctx.hid, account_id=a.id, security_id=sec.id, value=body.value,
                cost_basis=body.cost_basis, quantity=body.quantity, as_of=date.today())
    ctx.db.add(h)
    ctx.db.flush()
    ctx.db.refresh(a)
    a.balance = sum(float(x.value or 0) for x in a.holdings)
    a.balance_as_of = date.today()
    ctx.log("holding.create", "holding", h.id)
    return account_out(a)


@router.delete("/holdings/{holding_id}", status_code=204)
def delete_holding(holding_id: str, ctx: Ctx = Depends(get_writer)):
    h = ctx.owned(Holding, holding_id)
    a = ctx.owned(Account, h.account_id)
    ctx.db.delete(h)
    ctx.db.flush()
    ctx.db.refresh(a)
    a.balance = sum(float(x.value or 0) for x in a.holdings)
    ctx.log("holding.delete", "holding", holding_id)
    return Response(status_code=204)


@router.get("/securities")
def list_securities(ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.scalars(select(Security).where(Security.household_id == ctx.hid).order_by(Security.symbol))
    return [row_dict(s) for s in rows]


@router.get("/analytics/portfolio")
def portfolio_analytics(ctx: Ctx = Depends(get_ctx)):
    """Investment mix, concentration and look-through across all accounts."""
    accounts = list(ctx.db.scalars(select(Account).where(Account.household_id == ctx.hid)).unique())
    names = {c.key: c.name for c in ctx.db.scalars(select(AssetClass).where(AssetClass.household_id == ctx.hid))}
    out = analyze(holding_inputs(accounts), names)
    out["as_of"] = max((a.balance_as_of.isoformat() for a in accounts if a.balance_as_of), default=None)
    out["data_note"] = ("Values are the latest you entered or imported. Look-through uses composition data "
                        "stored with each fund; funds without it are listed under 'not covered'.")
    return out


@router.get("/networth")
def net_worth(ctx: Ctx = Depends(get_ctx)):
    def rows(model):
        return list(ctx.db.scalars(select(model).where(model.household_id == ctx.hid)).unique())
    accounts = rows(Account)
    by_type: dict[str, float] = {}
    for a in accounts:
        v = sum(float(h.value or 0) for h in a.holdings) if a.holdings else float(a.balance or 0)
        by_type[a.tax_type] = by_type.get(a.tax_type, 0) + v
    property_value = sum(float(r.value) for r in rows(RealEstate))
    business_value = sum(float(b.value) for b in rows(Business))
    debts = sum(float(x.balance) for x in rows(Liability))
    investments = sum(by_type.values())
    return {
        "investments": round(investments, 2),
        "investments_by_type": {k: round(v, 2) for k, v in by_type.items()},
        "property": round(property_value, 2),
        "businesses": round(business_value, 2),
        "debts": round(debts, 2),
        "net_worth": round(investments + property_value + business_value - debts, 2),
        "as_of": date.today().isoformat(),
        "note": "Based on the values you entered or imported; not live market data.",
    }


# ----------------------------------------------------------------------------- generic CRUD


def crud(path: str, model, schema: type[In], *, member_field: bool = False, validate=None):
    """Register list/create/update/delete routes for a simple household-owned table."""
    entity = model.__tablename__

    def list_(ctx: Ctx = Depends(get_ctx)):
        return [row_dict(r) for r in ctx.db.scalars(
            select(model).where(model.household_id == ctx.hid).order_by(model.created_at))]

    def apply(ctx: Ctx, row, body) -> None:
        if member_field:
            check_member(ctx, getattr(body, "member_id", None))
        if validate:
            validate(ctx, body)
        for k, v in body.model_dump().items():
            setattr(row, k, v)

    def create(body, ctx: Ctx = Depends(get_writer)):
        row = model(household_id=ctx.hid)
        apply(ctx, row, body)
        ctx.db.add(row)
        ctx.db.flush()
        ctx.log(f"{entity}.create", entity, row.id)
        return row_dict(row)

    def update(row_id: str, body, ctx: Ctx = Depends(get_writer)):
        row = ctx.owned(model, row_id)
        apply(ctx, row, body)
        ctx.db.flush()
        ctx.log(f"{entity}.update", entity, row.id)
        return row_dict(row)

    def delete(row_id: str, ctx: Ctx = Depends(get_writer)):
        ctx.db.delete(ctx.owned(model, row_id))
        ctx.log(f"{entity}.delete", entity, row_id)
        return Response(status_code=204)

    # Annotations are set explicitly because the body type is only known here.
    for fn in (list_, create, update, delete):
        fn.__annotations__ = {k: v for k, v in {"row_id": str, "ctx": Ctx}.items()
                              if k in fn.__code__.co_varnames[:fn.__code__.co_argcount]}
    create.__annotations__["body"] = schema
    update.__annotations__["body"] = schema
    router.add_api_route(f"/{path}", list_, methods=["GET"], name=f"list_{entity}")
    router.add_api_route(f"/{path}", create, methods=["POST"], status_code=201, name=f"create_{entity}")
    router.add_api_route(f"/{path}/{{row_id}}", update, methods=["PUT"], name=f"update_{entity}")
    router.add_api_route(f"/{path}/{{row_id}}", delete, methods=["DELETE"], status_code=204, name=f"delete_{entity}")


class IncomeIn(In):
    name: str = Field(min_length=1, max_length=120)
    member_id: str | None = None
    kind: Literal["salary", "pension", "annuity", "rental", "business", "other"] = "salary"
    amount: float = Field(ge=0)
    start_year: int | None = Field(None, ge=1950, le=2150)
    end_year: int | None = Field(None, ge=1950, le=2150)
    ends_at_retirement: bool = False
    growth_mode: Literal["inflation", "fixed", "none"] = "inflation"
    growth_rate: float = Field(0, ge=-0.2, le=0.2)
    tax_treatment: Literal["earned", "ordinary", "tax_free"] = "ordinary"
    survivor_pct: float = Field(0, ge=0, le=1)

    @model_validator(mode="after")
    def _check(self):
        if self.start_year and self.end_year and self.end_year < self.start_year:
            raise ValueError("The end year is before the start year.")
        if self.tax_treatment == "earned" and self.member_id is None:
            raise ValueError("Please choose whose pay this is.")
        return self


class PensionIn(In):
    name: str = Field(min_length=1, max_length=120)
    member_id: str
    annual_amount: float = Field(ge=0)
    start_age: int = Field(65, ge=40, le=100)
    has_cola: bool = False
    survivor_pct: float = Field(0.5, ge=0, le=1)


class ExpenseIn(In):
    name: str = Field(min_length=1, max_length=120)
    amount: float = Field(ge=0)
    category: Literal["essential", "discretionary"] = "essential"
    kind: Literal["living", "healthcare", "housing", "one_time", "other"] = "living"
    start_year: int | None = Field(None, ge=1950, le=2150)
    end_year: int | None = Field(None, ge=1950, le=2150)
    starts_at_retirement: bool = False
    ends_at_retirement: bool = False
    inflation_mode: Literal["general", "healthcare", "none", "custom"] = "general"
    custom_rate: float = Field(0, ge=-0.2, le=0.3)
    survivor_pct: float | None = Field(None, ge=0, le=2)

    @model_validator(mode="after")
    def _check(self):
        if self.kind == "one_time":
            if self.start_year is None:
                raise ValueError("Please choose the year for this one-time expense.")
            self.end_year = self.start_year
        if self.start_year and self.end_year and self.end_year < self.start_year:
            raise ValueError("The end year is before the start year.")
        return self


class LiabilityIn(In):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["mortgage", "car_loan", "student_loan", "credit_card", "other"] = "mortgage"
    balance: float = Field(ge=0)
    interest_rate: float = Field(ge=0, le=0.5)
    monthly_payment: float = Field(ge=0)
    real_estate_id: str | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.balance > 0 and self.monthly_payment <= self.balance * self.interest_rate / 12:
            raise ValueError("The monthly payment does not cover the interest, so this debt would never be "
                             "paid off. Please check the numbers.")
        return self


class RealEstateIn(In):
    name: str = Field(min_length=1, max_length=120)
    value: float = Field(ge=0)
    cost_basis: float = Field(0, ge=0)
    growth_rate: float = Field(0.03, ge=-0.1, le=0.2)
    sale_year: int | None = Field(None, ge=2000, le=2150)
    sale_cost_pct: float = Field(0.06, ge=0, le=0.5)
    primary_residence: bool = True


class BusinessIn(In):
    name: str = Field(min_length=1, max_length=120)
    member_id: str | None = None
    value: float = Field(ge=0)
    cost_basis: float = Field(0, ge=0)
    growth_rate: float = Field(0.03, ge=-0.2, le=0.3)
    annual_income: float = Field(0, ge=0)
    sale_year: int | None = Field(None, ge=2000, le=2150)
    sale_cost_pct: float = Field(0.05, ge=0, le=0.5)


def _check_property(ctx: Ctx, body: LiabilityIn) -> None:
    if body.real_estate_id is not None:
        ctx.owned(RealEstate, body.real_estate_id)


crud("incomes", IncomeSource, IncomeIn, member_field=True)
crud("pensions", Pension, PensionIn, member_field=True)
crud("expenses", Expense, ExpenseIn)
crud("liabilities", Liability, LiabilityIn, validate=_check_property)
crud("real-estate", RealEstate, RealEstateIn)
crud("businesses", Business, BusinessIn, member_field=True)


@router.get("/transactions")
def list_transactions(limit: int = 200, ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.scalars(select(Transaction).where(Transaction.household_id == ctx.hid)
                          .order_by(Transaction.txn_date.desc()).limit(min(max(limit, 1), 1000)))
    return [row_dict(t) for t in rows]


# ----------------------------------------------------------------------------- import & sample data


class CsvIn(In):
    kind: Literal["accounts", "holdings", "transactions", "expenses"]
    content: str = Field(max_length=2_000_000)


@router.get("/import/templates")
def import_templates(ctx: Ctx = Depends(get_ctx)):
    return csv_import.TEMPLATES


@router.post("/import/csv")
def import_csv(body: CsvIn, ctx: Ctx = Depends(get_writer)):
    try:
        result = csv_import.import_csv(ctx.db, ctx.hid, body.kind, body.content)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    ctx.log("import.csv", detail={"kind": body.kind, "imported": result["imported"],
                                  "errors": len(result["errors"])})
    return result


@router.post("/sample-data")
def sample_data(ctx: Ctx = Depends(get_writer)):
    """Replace this household's data with a clearly labelled fictional example."""
    if ctx.role != "owner":
        raise HTTPException(403, "Only the owner can do this.")
    load_sample_data(ctx.db, ctx.household)
    ctx.plan().start_year = current_year()
    ctx.log("sample_data.load")
    return {"ok": True, "note": "Fictional sample data loaded. Every number is invented for illustration."}


@router.delete("/sample-data")
def clear_data(ctx: Ctx = Depends(get_writer)):
    if ctx.role != "owner":
        raise HTTPException(403, "Only the owner can do this.")
    from ..services.setup import clear_household_data
    clear_household_data(ctx.db, ctx.household)
    ctx.household.is_demo = False
    ctx.household.onboarding_complete = False
    ctx.household.filing_status = "single"
    ctx.household.name = f"{ctx.user.display_name}'s household"
    ctx.log("household.clear")
    return {"ok": True}
