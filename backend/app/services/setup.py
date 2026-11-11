"""Creating a household with sensible defaults, and the fictional sample data."""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from ..engine.models import Assumptions, default_asset_classes
from ..engine.taxrules import default_state_rate
from ..models import (
    Account,
    Allocation,
    AssetClass,
    AssumptionSet,
    Expense,
    Holding,
    Household,
    HouseholdAccess,
    IncomeSource,
    Liability,
    Member,
    Plan,
    RealEstate,
    Security,
    SSEstimate,
    User,
)

# Asset-class level look-through for a few broad index funds. These describe what
# each fund is designed to track (stable facts), not live holdings data.
REFERENCE_FUNDS = {
    "VTI": ("Total US stock market index fund", "us_stocks", [("us_stocks", 1.0)]),
    "VOO": ("S&P 500 index fund", "us_stocks", [("us_stocks", 1.0)]),
    "VXUS": ("Total international stock index fund", "intl_stocks", [("intl_stocks", 1.0)]),
    "BND": ("Total US bond market index fund", "bonds", [("bonds", 1.0)]),
    "VNQ": ("US real estate index fund", "real_estate", [("real_estate", 1.0)]),
}
REFERENCE_SOURCE = "Built-in reference: the asset class each index fund is designed to track"

ALLOCATION_PRESETS = {
    "cash": {"cash": 1.0},
    "conservative": {"us_stocks": 0.25, "intl_stocks": 0.05, "bonds": 0.60, "cash": 0.10},
    "balanced": {"us_stocks": 0.45, "intl_stocks": 0.15, "bonds": 0.35, "cash": 0.05},
    "growth": {"us_stocks": 0.60, "intl_stocks": 0.20, "bonds": 0.20},
    "aggressive": {"us_stocks": 0.70, "intl_stocks": 0.25, "bonds": 0.05},
}


def current_year() -> int:
    return date.today().year


def create_household(db: Session, user: User, name: str | None = None) -> Household:
    household = Household(owner_user_id=user.id, name=name or f"{user.display_name}'s household")
    db.add(household)
    db.flush()
    db.add(HouseholdAccess(household_id=household.id, user_id=user.id, role="owner"))
    for i, ac in enumerate(default_asset_classes()):
        db.add(AssetClass(household_id=household.id, sort_order=i, **ac.model_dump()))
    plan = Plan(household_id=household.id, name="My plan", is_baseline=True, start_year=current_year())
    db.add(plan)
    db.flush()
    assumptions = Assumptions()
    assumptions.state_tax.state = household.state
    assumptions.state_tax.rate = default_state_rate(household.state)
    db.add(AssumptionSet(household_id=household.id, plan_id=plan.id, version=1,
                         payload=assumptions.model_dump(mode="json"), note="Starting assumptions",
                         created_by=user.id))
    db.flush()
    return household


def clear_household_data(db: Session, household: Household) -> None:
    from ..models import (
        AIConversation,
        Business,
        MonteCarloRun,
        Pension,
        ProjectionResult,
        Report,
        RothStrategy,
        Scenario,
        Transaction,
    )
    for model in (Transaction, Holding, Allocation, Account, Security, IncomeSource, Pension, Expense,
                  Liability, RealEstate, Business, SSEstimate, Member, Scenario, ProjectionResult,
                  MonteCarloRun, RothStrategy, Report, AIConversation):
        for row in db.query(model).filter(model.household_id == household.id).all():
            db.delete(row)
    db.flush()


def load_sample_data(db: Session, household: Household) -> None:
    """Fill the household with a FICTIONAL example couple so the app can be explored.
    Every number here is invented for illustration."""
    clear_household_data(db, household)
    year = current_year()
    hid = household.id
    household.name = "Sample household (fictional)"
    household.filing_status = "mfj"
    household.state = "FL"
    household.is_demo = True
    household.onboarding_complete = True

    pat = Member(household_id=hid, name="Pat", relationship_kind="self", birth_year=year - 62,
                 retirement_age=66, life_expectancy=92)
    sam = Member(household_id=hid, name="Sam", relationship_kind="spouse", birth_year=year - 60,
                 retirement_age=65, life_expectancy=95)
    db.add_all([pat, sam])
    db.flush()
    db.add_all([
        SSEstimate(household_id=hid, member_id=pat.id, monthly_benefit=2900, claim_age=67,
                   source="Sample data", as_of=date.today()),
        SSEstimate(household_id=hid, member_id=sam.id, monthly_benefit=1700, claim_age=67,
                   source="Sample data", as_of=date.today()),
    ])

    secs = {}
    for symbol, (name, klass, parts) in REFERENCE_FUNDS.items():
        s = Security(household_id=hid, symbol=symbol, name=name, asset_class_key=klass, is_fund=True,
                     composition=[{"kind": "asset_class", "key": k, "weight": w} for k, w in parts],
                     composition_source=REFERENCE_SOURCE, composition_as_of=date.today())
        secs[symbol] = s
        db.add(s)
    secs["EXAMPLECO"] = Security(household_id=hid, symbol="EXAMPLECO", name="Example Co. (employer stock)",
                                 asset_class_key="us_stocks", is_fund=False)
    db.add(secs["EXAMPLECO"])
    db.flush()

    def account(name, tax_type, member, holdings=None, balance=0.0, preset=None, **kw):
        acct = Account(household_id=hid, name=name, tax_type=tax_type, member_id=member.id if member else None,
                       balance=balance, source="manual", balance_as_of=date.today(), **kw)
        db.add(acct)
        db.flush()
        for symbol, value, basis in holdings or []:
            db.add(Holding(household_id=hid, account_id=acct.id, security_id=secs[symbol].id, value=value,
                           cost_basis=basis, as_of=date.today()))
        for key, weight in (ALLOCATION_PRESETS[preset] if preset else {}).items():
            db.add(Allocation(household_id=hid, account_id=acct.id, asset_class_key=key, weight=weight))
        if holdings:
            acct.balance = sum(h[1] for h in holdings)
        return acct

    account("Pat's 401(k)", "traditional", pat, annual_contribution=18000, employer_match=6000,
            institution="Example Retirement Services",
            holdings=[("VTI", 390000, None), ("VXUS", 110000, None), ("BND", 200000, None)])
    account("Sam's IRA", "traditional", sam, institution="Example Brokerage",
            holdings=[("VOO", 120000, None), ("BND", 80000, None)])
    account("Sam's Roth IRA", "roth", sam, institution="Example Brokerage",
            holdings=[("VTI", 95000, None), ("VNQ", 15000, None)])
    account("Joint brokerage", "taxable", None, institution="Example Brokerage",
            holdings=[("VTI", 140000, 80000), ("EXAMPLECO", 90000, 30000), ("BND", 50000, 48000)])
    account("Savings", "cash", None, balance=45000, preset="cash", institution="Example Bank")

    db.add_all([
        IncomeSource(household_id=hid, member_id=pat.id, name="Pat's salary", kind="salary", amount=115000,
                     ends_at_retirement=True, tax_treatment="earned"),
        IncomeSource(household_id=hid, member_id=sam.id, name="Sam's salary", kind="salary", amount=58000,
                     ends_at_retirement=True, tax_treatment="earned"),
        Expense(household_id=hid, name="Everyday living (food, bills, car)", amount=58000, category="essential"),
        Expense(household_id=hid, name="Health costs (out of pocket)", amount=7000, category="essential",
                kind="healthcare", inflation_mode="healthcare"),
        Expense(household_id=hid, name="Travel and hobbies", amount=16000, category="discretionary"),
        Expense(household_id=hid, name="New roof", amount=25000, category="essential", kind="one_time",
                start_year=year + 3, end_year=year + 3),
    ])
    home = RealEstate(household_id=hid, name="Home", value=520000, cost_basis=260000, growth_rate=0.03,
                      primary_residence=True, value_as_of=date.today())
    db.add(home)
    db.flush()
    db.add(Liability(household_id=hid, name="Mortgage", kind="mortgage", balance=96000, interest_rate=0.0375,
                     monthly_payment=1450, real_estate_id=home.id))
    db.flush()
