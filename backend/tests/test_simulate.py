"""Projection engine validation against independently calculated benchmarks."""
import numpy as np
import pytest

from app.engine.models import (
    Account,
    AssetClass,
    Assumptions,
    Expense,
    Guardrails,
    IlliquidAsset,
    Income,
    Liability,
    Member,
    PlanInput,
    RothConversion,
    SocialSecurity,
    StateTax,
)
from app.engine.projection import project
from app.engine.simulate import find_root, simulate
from app.engine.taxrules import load_rules
from tests.conftest import make_plan

FLAT = [AssetClass(key="g", name="Growth", expected_return=0.05, volatility=0.1),
        AssetClass(key="c", name="Cash", expected_return=0.0, volatility=0.0, proxy="cash")]


def single(birth_year=1960, accounts=(), incomes=(), expenses=(), life=90, retire=60, ss=0, claim=67,
           basis="at_fra", **assumptions):
    a = dict(model_medicare_premiums=False)
    a.update(assumptions)
    return PlanInput(
        start_year=2026, filing_status="single",
        members=[Member(id="m", name="Pat", birth_year=birth_year, retirement_age=retire, life_expectancy=life,
                        social_security=SocialSecurity(monthly_benefit=ss, claim_age=claim, basis=basis))],
        accounts=list(accounts), incomes=list(incomes), expenses=list(expenses),
        asset_classes=FLAT, correlations={}, assumptions=Assumptions(**a),
    )


def acct(tax_type, balance, key="g", owner="m", **kw):
    return Account(id=tax_type, name=tax_type, owner=owner if tax_type not in ("taxable", "cash") else "joint",
                   tax_type=tax_type, balance=balance, allocation={key: 1.0}, **kw)


def test_compounding():
    res = simulate(single(accounts=[acct("roth", 100_000)]))
    n = len(res.years)
    expected = 100_000 * 1.05 ** np.arange(1, n + 1)
    assert res.series["portfolio"][0] == pytest.approx(expected)
    assert res.series["tax_total"].sum() == 0


def test_fees_reduce_growth():
    res = simulate(single(accounts=[acct("roth", 100_000, annual_fee=0.01)]))
    assert res.series["portfolio"][0, 9] == pytest.approx(100_000 * 1.04 ** 10)


def test_inflation_of_expenses_and_real_dollars():
    p = single(accounts=[acct("roth", 2_000_000, key="c")], expenses=[Expense(id="e", name="Living", amount=10_000)],
               inflation=0.03)
    res = simulate(p)
    t = np.arange(len(res.years))
    assert res.series["spending_total"][0] == pytest.approx(10_000 * 1.03 ** t)
    assert res.price_index == pytest.approx(1.03 ** t)
    assert res.real("spending_total")[0] == pytest.approx(np.full(len(t), 10_000.0))


def test_healthcare_and_custom_inflation():
    p = single(accounts=[acct("roth", 5_000_000, key="c")], expenses=[
        Expense(id="h", name="Health", amount=1_000, kind="healthcare", inflation_mode="healthcare"),
        Expense(id="n", name="Fixed", amount=1_000, inflation_mode="none"),
        Expense(id="c", name="Custom", amount=1_000, inflation_mode="custom", custom_rate=0.10),
    ], healthcare_inflation=0.06)
    res = simulate(p)
    assert res.series["spending_total"][0, 10] == pytest.approx(1_000 * 1.06 ** 10 + 1_000 + 1_000 * 1.10 ** 10)


def test_cash_flow_identity_every_year(plan):
    """Money in = money out, to the cent, in every year."""
    s = simulate(plan).series
    money_in = (s["wages"] + s["other_income"] + s["social_security"] + s["tax_free_income"]
                + s["asset_sale_proceeds"] + s["withdrawals_total"])
    money_out = s["contributions"] + s["tax_total"] + s["spending_total"] + s["surplus_saved"]
    assert money_in == pytest.approx(money_out, abs=0.02)


def test_balance_identity_roth_only():
    """End balance = (start - withdrawals) x (1 + return)."""
    p = single(accounts=[acct("roth", 500_000)], expenses=[Expense(id="e", name="Living", amount=30_000)])
    s = simulate(p).series
    bal = 500_000.0
    for t in range(10):
        bal = (bal - s["withdrawals_total"][0, t]) * 1.05
        assert s["portfolio"][0, t] == pytest.approx(bal)
    assert s["withdrawals_total"][0, 0] == pytest.approx(30_000)


def test_withdrawal_order_taxable_first(plan):
    s = simulate(plan).series
    voluntary_trad = s["withdrawals_traditional"][0] - s["rmd"][0]
    for t in range(1, len(voluntary_trad)):
        if voluntary_trad[t] > 1:
            # pre-tax money is only touched once savings and taxable accounts were emptied
            assert s["balance_cash"][0, t] + s["balance_taxable"][0, t] < 1 + s["surplus_saved"][0, t] * 1.2
        if s["withdrawals_roth"][0, t] > 1:
            assert s["balance_traditional"][0, t] < 1


def test_withdrawal_strategies_differ_but_all_fund_spending(plan):
    totals = {}
    for strat in ("taxable_first", "traditional_first", "roth_first", "proportional"):
        p = plan.model_copy(deep=True)
        p.assumptions.withdrawal_strategy = strat
        s = simulate(p).series
        assert s["shortfall"].sum() == 0
        totals[strat] = s["tax_total"].sum()
    assert len({round(v) for v in totals.values()}) == 4


def test_proportional_withdrawal_split():
    p = single(accounts=[acct("roth", 300_000, key="c"), acct("cash", 100_000, key="c")],
               expenses=[Expense(id="e", name="Living", amount=40_000)], withdrawal_strategy="proportional")
    s = simulate(p).series
    assert s["withdrawals_roth"][0, 0] == pytest.approx(30_000, abs=0.01)
    assert s["withdrawals_cash"][0, 0] == pytest.approx(10_000, abs=0.01)


def test_rmd_matches_irs_table():
    # born 1950 -> age 76 in 2026 -> divisor 23.7
    p = single(birth_year=1950, life=95, accounts=[acct("traditional", 500_000, key="c")])
    s = simulate(p).series
    assert s["rmd"][0, 0] == pytest.approx(500_000 / 23.7)
    # the unspent RMD (after tax) is saved, not lost
    assert s["surplus_saved"][0, 0] == pytest.approx(s["rmd"][0, 0] - s["tax_total"][0, 0], abs=0.01)
    # next year: prior year-end balance / 22.9
    assert s["rmd"][0, 1] == pytest.approx(s["balance_traditional"][0, 0] / 22.9)


def test_no_rmd_before_start_age():
    p = single(birth_year=1960, accounts=[acct("traditional", 500_000, key="c")])
    res = simulate(p)
    rmd = res.series["rmd"][0]
    assert rmd[: 2035 - 2026].sum() == 0            # ages 66-74
    assert rmd[2035 - 2026] == pytest.approx(res.series["balance_traditional"][0, 2034 - 2026] / 24.6)


def test_retiree_tax_matches_hand_calculation():
    # Age 67 in 2026: pension 40,000 + Social Security 24,000 -> federal tax 4,030 (see test_tax.py)
    p = single(birth_year=1959, ss=2_000, claim=66, basis="as_claimed",
               incomes=[Income(id="p", name="Pension", kind="pension", owner="m", amount=40_000)],
               expenses=[Expense(id="e", name="Living", amount=30_000)],
               accounts=[acct("roth", 10_000)])
    row = project(p)["rows"][0]
    assert row["social_security"] == 24_000
    assert row["taxable_ss"] == 19_800
    assert row["agi"] == 59_800
    assert row["deduction"] == 24_150
    assert row["tax_federal_ordinary"] == 4_030
    assert row["tax_total"] == 4_030
    assert row["surplus_saved"] == pytest.approx(64_000 - 30_000 - 4_030)


def test_wages_payroll_tax_and_pretax_contribution():
    # wages 100,000, pre-tax 401k 10,000, age 50 in 2026
    # FICA 7.65% x 100,000 = 7,650; taxable income 90,000 - 16,100 = 73,900
    # tax 1,240 + 4,560 + 22% x 23,500 = 5,170 -> 10,970
    p = single(birth_year=1976, retire=65,
               incomes=[Income(id="w", name="Job", owner="m", amount=100_000, tax_treatment="earned", end_year=2040)],
               accounts=[acct("traditional", 0, key="c", annual_contribution=10_000, employer_match=3_000)],
               expenses=[Expense(id="e", name="Living", amount=50_000)])
    row = project(p)["rows"][0]
    assert row["tax_payroll"] == 7_650
    assert row["tax_federal_ordinary"] == 10_970
    assert row["contributions"] == 10_000
    assert row["employer_match"] == 3_000
    assert row["balance_traditional"] == 13_000
    assert row["surplus_saved"] == pytest.approx(100_000 - 10_000 - 7_650 - 10_970 - 50_000)


def test_early_withdrawal_penalty():
    p = single(birth_year=1976, retire=50, accounts=[acct("traditional", 500_000, key="c")],
               expenses=[Expense(id="e", name="Living", amount=20_000)])
    row = project(p)["rows"][0]
    assert row["tax_penalty"] == pytest.approx(0.10 * row["withdrawals_traditional"], abs=0.01)
    assert row["tax_penalty"] > 0
    older = single(birth_year=1960, accounts=[acct("traditional", 500_000, key="c")],
                   expenses=[Expense(id="e", name="Living", amount=20_000)])
    assert project(older)["rows"][0]["tax_penalty"] == 0


def test_taxable_account_gains_and_basis():
    # basis is 40% of the balance -> 60% of each dollar withdrawn is gain
    p = single(accounts=[Account(id="t", name="Brokerage", owner="joint", tax_type="taxable", balance=100_000,
                                 cost_basis=40_000, allocation={"c": 1.0})],
               expenses=[Expense(id="e", name="Living", amount=10_000)])
    row = project(p)["rows"][0]
    assert row["withdrawals_taxable"] == pytest.approx(10_000, abs=0.01)
    assert row["realized_gains"] == pytest.approx(6_000, abs=0.01)
    assert row["tax_total"] == 0  # 6,000 of gains is below the standard deduction


def test_state_tax_applied():
    p = single(birth_year=1976, retire=65, state_tax=StateTax(state="XX", rate=0.05),
               incomes=[Income(id="w", name="Job", owner="m", amount=100_000, tax_treatment="earned", end_year=2040)],
               expenses=[Expense(id="e", name="Living", amount=10_000)])
    assert project(p)["rows"][0]["tax_state"] == pytest.approx(5_000)


def test_shortfall_reported_when_money_runs_out():
    p = single(accounts=[acct("roth", 50_000, key="c")], expenses=[Expense(id="e", name="Living", amount=30_000)])
    out = project(p)
    assert out["summary"]["funded"] is False
    assert out["summary"]["first_shortfall_year"] == 2027
    rows = out["rows"]
    assert rows[0]["shortfall"] == 0
    assert rows[1]["shortfall"] == pytest.approx(30_000 * 1.025 - 20_000)
    assert rows[1]["spending_total"] == pytest.approx(20_000)
    assert rows[5]["portfolio"] == 0


def test_social_security_claiming_cola_and_reduction():
    p = single(birth_year=1964, ss=2_000, claim=62, accounts=[acct("roth", 1_000_000, key="c")],
               ss_reduction_pct=0.2, ss_reduction_year=2034)
    s = simulate(p).series["social_security"][0]
    # claims in 2026 at 62: 70% of 24,000 = 16,800, growing with 2.5% inflation
    assert s[0] == pytest.approx(16_800)
    assert s[5] == pytest.approx(16_800 * 1.025 ** 5)
    assert s[8] == pytest.approx(16_800 * 1.025 ** 8 * 0.8)


def test_spousal_and_survivor_benefits():
    # born 1960 -> full retirement age 67, so claiming at 67 means benefit = full amount
    members = [
        Member(id="a", name="A", birth_year=1960, retirement_age=60, life_expectancy=75,
               social_security=SocialSecurity(monthly_benefit=3_000, claim_age=67)),
        Member(id="b", name="B", birth_year=1960, retirement_age=60, life_expectancy=90,
               social_security=SocialSecurity(monthly_benefit=500, claim_age=67)),
    ]
    p = PlanInput(start_year=2026, filing_status="mfj", members=members, asset_classes=FLAT, correlations={},
                  accounts=[Account(id="c", name="c", owner="joint", tax_type="cash", balance=100_000,
                                    allocation={"c": 1.0})],
                  assumptions=Assumptions(model_medicare_premiums=False))
    res = simulate(p)
    ss = res.series["social_security"][0]
    assert ss[0] == 0                                   # 2026: age 66, not claimed yet
    # 2027, both alive: A 36,000; B gets the spousal top-up to 50% of A's benefit = 18,000
    assert ss[1] == pytest.approx(54_000 * 1.025)
    # A dies at 75 (2035). From 2036 B keeps the larger benefit: 36,000 (plus COLA)
    t = 2036 - 2026
    assert ss[t] == pytest.approx(36_000 * 1.025 ** t)
    assert res.filing_status[2035 - 2026] == "mfj"
    assert res.filing_status[t] == "single"
    assert res.ages["a"][t] is None and res.ages["b"][t] == 76
    no_spousal = p.model_copy(deep=True)
    no_spousal.assumptions.spousal_benefits = False
    assert simulate(no_spousal).series["social_security"][0, 1] == pytest.approx(42_000 * 1.025)


def test_survivor_expenses_and_pension():
    members = [Member(id="a", name="A", birth_year=1950, retirement_age=60, life_expectancy=80),
               Member(id="b", name="B", birth_year=1950, retirement_age=60, life_expectancy=90)]
    p = PlanInput(start_year=2026, filing_status="mfj", members=members, asset_classes=FLAT, correlations={},
                  accounts=[Account(id="c", name="c", owner="joint", tax_type="cash", balance=3_000_000,
                                    allocation={"c": 1.0})],
                  incomes=[Income(id="p", name="Pension", owner="a", kind="pension", amount=20_000,
                                  growth_mode="none", survivor_pct=0.5)],
                  expenses=[Expense(id="e", name="Living", amount=50_000, inflation_mode="none"),
                            Expense(id="k", name="Keep", amount=10_000, inflation_mode="none", survivor_pct=1.0)],
                  assumptions=Assumptions(model_medicare_premiums=False, survivor_expense_pct=0.7))
    s = simulate(p).series
    assert s["spending_total"][0, 4] == pytest.approx(60_000)          # 2030, both alive
    assert s["spending_total"][0, 5] == pytest.approx(45_000)          # 2031, after first death
    assert s["other_income"][0, 4] == 20_000 and s["other_income"][0, 5] == 10_000


def test_fixed_roth_conversion_moves_money_and_is_taxed():
    base = single(accounts=[acct("traditional", 400_000, key="c"), acct("cash", 200_000, key="c")])
    conv = base.model_copy(deep=True)
    conv.assumptions.roth_conversion = RothConversion(mode="fixed", amount=50_000, start_year=2026, end_year=2026)
    row = project(conv)["rows"][0]
    assert row["roth_conversion"] == 50_000
    assert row["balance_traditional"] == 350_000
    assert row["balance_roth"] == 50_000
    # age 66: deduction 16,100 + 2,050 + 6,000 senior = 24,150; taxable income 25,850
    # tax 1,240 + 12% x 13,450 = 1,614 -> 2,854, paid from savings
    assert row["deduction"] == 24_150
    assert row["tax_federal_ordinary"] == 2_854
    assert row["withdrawals_cash"] == pytest.approx(2_854, abs=0.01)
    assert project(base)["rows"][0]["tax_total"] == 0


def test_fill_bracket_conversion_hits_the_bracket_top():
    p = single(accounts=[acct("traditional", 2_000_000, key="c"), acct("cash", 500_000, key="c")],
               ss=2_500, claim=67, expenses=[Expense(id="e", name="Living", amount=60_000)])
    p.assumptions.roth_conversion = RothConversion(mode="fill_bracket", bracket_rate=0.22, start_year=2026,
                                                   end_year=2030)
    res = simulate(p)
    for t in range(5):
        year = 2026 + t
        top = load_rules(2026).params(year, "single", index_factor=1.025 ** t).bracket_top(0.22)
        assert res.series["ordinary_taxable_income"][0, t] == pytest.approx(top, abs=1.5)
        assert res.series["roth_conversion"][0, t] > 0
    assert res.series["roth_conversion"][0, 5:].sum() == 0


def test_fill_magi_conversion_respects_ceiling():
    p = single(accounts=[acct("traditional", 2_000_000, key="c"), acct("cash", 500_000, key="c")])
    p.assumptions.roth_conversion = RothConversion(mode="fill_magi", amount=109_000, start_year=2026, end_year=2028)
    res = simulate(p)
    assert res.series["agi"][0, :3] == pytest.approx(109_000 * 1.025 ** np.arange(3), abs=1.5)


def test_liability_amortisation():
    p = single(accounts=[acct("cash", 2_000_000, key="c")],
               expenses=[], incomes=[])
    p.liabilities = [Liability(id="l", name="Mortgage", balance=100_000, interest_rate=0.06, monthly_payment=1_000)]
    s = simulate(p).series
    r = 0.06 / 12
    expected = 100_000 * (1 + r) ** 12 - 1_000 * ((1 + r) ** 12 - 1) / r
    assert s["debt_payments"][0, 0] == pytest.approx(12_000)
    assert s["liabilities"][0, 0] == pytest.approx(expected)
    assert s["liabilities"][0, -1] == 0
    assert s["net_worth"][0, 0] == pytest.approx(s["portfolio"][0, 0] - expected)


def test_home_sale_with_exclusion_and_mortgage_payoff():
    p = single(accounts=[acct("cash", 100_000, key="c")])
    p.assets = [IlliquidAsset(id="home", name="Home", value=600_000, cost_basis=200_000, growth_rate=0.0,
                              sale_year=2028, sale_cost_pct=0.05, primary_residence=True)]
    p.liabilities = [Liability(id="l", name="Mortgage", balance=50_000, interest_rate=0.0, monthly_payment=0,
                               linked_asset_id="home")]
    rows = project(p)["rows"]
    assert rows[1]["other_assets"] == 600_000
    sale = rows[2]
    # net proceeds 570,000; gain 370,000 - 250,000 exclusion = 120,000; mortgage 50,000 repaid
    assert sale["asset_sale_proceeds"] == 520_000
    assert sale["realized_gains"] == pytest.approx(120_000)
    assert sale["other_assets"] == 0 and sale["liabilities"] == 0
    # 2028, age 68, all income is long-term gain (AGI 120,000):
    # deduction (16,100 + 2,050) x 1.025^2 + senior 6,000 - 6% x (120,000 - 75,000) = 3,300
    ded = (16_100 + 2_050) * 1.025 ** 2 + 3_300
    zero_top = 49_450 * 1.025 ** 2
    assert sale["tax_federal_ltcg"] == pytest.approx(0.15 * (120_000 - ded - zero_top), abs=0.01)


def test_hsa_pays_healthcare_tax_free():
    p = single(accounts=[acct("hsa", 50_000, key="c"), acct("cash", 500_000, key="c")],
               expenses=[Expense(id="h", name="Health", amount=6_000, kind="healthcare", inflation_mode="none"),
                         Expense(id="e", name="Living", amount=20_000, inflation_mode="none")])
    row = project(p)["rows"][0]
    assert row["hsa_withdrawals"] == 6_000
    assert row["withdrawals_cash"] == pytest.approx(20_000, abs=0.01)
    assert row["balance_hsa"] == 44_000


def test_medicare_premiums_and_irmaa_lookback():
    p = single(birth_year=1955, accounts=[acct("cash", 3_000_000, key="c")], model_medicare_premiums=True,
               prior_magi=[150_000, 90_000], healthcare_inflation=0.05)
    rows = project(p)["rows"]
    # 2026 uses 2024 income 150,000 -> tier 2: 202.90 + 202.90 + 37.50
    assert rows[0]["medicare_premiums"] == pytest.approx(12 * (202.90 + 202.90 + 37.50))
    # 2027 uses 2025 income 90,000 -> standard premium, grown by healthcare inflation
    assert rows[1]["medicare_premiums"] == pytest.approx(12 * 202.90 * 1.05)


def test_deterministic_and_hash(plan):
    a, b = project(plan), project(make_plan())
    assert a == b
    assert a["meta"]["plan_hash"] == plan.content_hash()
    changed = make_plan()
    changed.assumptions.inflation = 0.03
    assert changed.content_hash() != plan.content_hash()
    assert project(changed)["summary"] != a["summary"]


def test_two_tax_rule_versions_used_when_plan_starts_in_2025():
    p = single(accounts=[acct("cash", 100_000, key="c")])
    p = p.model_copy(update={"start_year": 2025})
    assert project(p)["meta"]["tax_rule_versions"] == ["2025.2", "2026.1"]


def test_guardrails_cut_discretionary_only():
    p = single(accounts=[acct("roth", 1_000_000)], expenses=[
        Expense(id="e", name="Essentials", amount=30_000),
        Expense(id="d", name="Fun", amount=20_000, category="discretionary")])
    p.assumptions.guardrails = Guardrails(enabled=True)
    n = p.end_year - p.start_year + 1
    returns = np.full((1, n, 2), 0.05)
    returns[0, 1:4, 0] = -0.25  # three bad years
    s = simulate(p, returns=returns).series
    assert s["spending_multiplier"][0, 0] == 1.0
    assert s["spending_multiplier"][0].min() < 1.0
    assert s["expenses_essential"][0] == pytest.approx(30_000 * 1.025 ** np.arange(n))
    assert (s["expenses_discretionary"][0] <= s["expenses_discretionary_planned"][0] * 1.5 + 0.01).all()
    cut_year = int(np.argmax(s["spending_multiplier"][0] < 1.0))
    assert s["expenses_discretionary"][0, cut_year] == pytest.approx(
        s["expenses_discretionary_planned"][0, cut_year] * 0.9)


def test_guardrails_raise_spending_after_good_returns():
    p = single(accounts=[acct("roth", 1_000_000)], expenses=[
        Expense(id="e", name="Essentials", amount=30_000),
        Expense(id="d", name="Fun", amount=20_000, category="discretionary")])
    p.assumptions.guardrails = Guardrails(enabled=True, max_multiplier=1.2)
    n = p.end_year - p.start_year + 1
    s = simulate(p, returns=np.full((1, n, 2), 0.15)).series
    assert s["spending_multiplier"][0].max() == pytest.approx(1.2, abs=0.02)
    assert s["spending_multiplier"][0].max() <= 1.2 + 1e-9


def test_find_root_piecewise_linear():
    def f(x):
        return np.where(x < 10, 0.5 * x - 20, 2.0 * x - 35)
    lo, hi = np.zeros(3), np.array([100.0, 100.0, 100.0])
    root = find_root(f, lo, hi, f(lo), f(hi), xtol=1e-9, ftol=1e-9, max_iter=80)
    assert root == pytest.approx(17.5)


def test_validation_errors():
    with pytest.raises(ValueError, match="allocation"):
        Account(id="x", name="x", tax_type="roth", owner="m", balance=1, allocation={"g": 0.5})
    with pytest.raises(ValueError, match="single owner"):
        Account(id="x", name="x", tax_type="roth", owner="joint", balance=1, allocation={"g": 1})
    with pytest.raises(ValueError, match="two household members"):
        PlanInput(start_year=2026, filing_status="mfj",
                  members=[Member(id="m", name="P", birth_year=1960)])
    with pytest.raises(ValueError, match="unknown asset class"):
        single(accounts=[acct("roth", 1, key="nope")])
