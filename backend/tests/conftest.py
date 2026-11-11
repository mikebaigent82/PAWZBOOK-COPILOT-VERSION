import pytest

from app.engine.models import Account, Assumptions, Expense, Income, Member, PlanInput, SocialSecurity


def make_plan(**overrides) -> PlanInput:
    members = [
        Member(id="a", name="Al", birth_year=1962, retirement_age=66, life_expectancy=92,
               social_security=SocialSecurity(monthly_benefit=2800, claim_age=67)),
        Member(id="b", name="Bea", birth_year=1964, retirement_age=65, life_expectancy=95,
               social_security=SocialSecurity(monthly_benefit=1500, claim_age=67)),
    ]
    accounts = [
        Account(id="brokerage", name="Brokerage", owner="joint", tax_type="taxable", balance=300_000,
                cost_basis=180_000, allocation={"us_stocks": 0.6, "bonds": 0.4}),
        Account(id="k401", name="401k", owner="a", tax_type="traditional", balance=900_000,
                allocation={"us_stocks": 0.6, "bonds": 0.4}, annual_contribution=20_000, employer_match=5_000),
        Account(id="roth", name="Roth", owner="b", tax_type="roth", balance=150_000,
                allocation={"us_stocks": 0.8, "bonds": 0.2}),
        Account(id="savings", name="Savings", owner="joint", tax_type="cash", balance=50_000,
                allocation={"cash": 1.0}),
    ]
    incomes = [Income(id="salary", name="Salary", owner="a", kind="salary", amount=140_000, end_year=2027,
                      tax_treatment="earned")]
    expenses = [
        Expense(id="living", name="Living", amount=70_000),
        Expense(id="travel", name="Travel", amount=20_000, category="discretionary"),
    ]
    data = dict(start_year=2026, filing_status="mfj", members=members, accounts=accounts, incomes=incomes,
                expenses=expenses, assumptions=Assumptions())
    data.update(overrides)
    return PlanInput(**data)


@pytest.fixture
def plan() -> PlanInput:
    return make_plan()
