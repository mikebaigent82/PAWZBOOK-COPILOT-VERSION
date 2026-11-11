"""Core year-by-year simulation.

One function, :func:`simulate`, drives both the deterministic projection (one
path using the expected returns) and Monte Carlo (many paths of random
returns), so both always follow exactly the same rules.

Timing convention (applies to every year):
  1. Balances at the start of the year are the prior year-end balances.
  2. Income is received, contributions are made, required minimum distributions
     (RMDs), Roth conversions and any withdrawals needed to pay for spending
     and taxes are taken -- all at the start of the year.
  3. The remaining balance earns that year's return (net of fees).
Taxes for a year are paid in that same year.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import social_security as ssmod
from .models import JOINT, Account, PlanInput
from .rmd import rmd_fraction
from .tax import federal_income_tax, irmaa_monthly, payroll_tax, state_income_tax
from .taxrules import TaxRuleSet, YearTaxParams, available_years, load_rules

Array = np.ndarray

SOLVER_MAX_ITER = 80
CASH_TOLERANCE = 0.005  # dollars: withdrawals are solved to within half a cent
CONVERSION_TOLERANCE = 1.0  # dollars: "fill" conversions land within $1 of the target
PENALTY_AGE = 60  # integer-age proxy for the 59 1/2 rule

WITHDRAWAL_ORDER = {
    "taxable_first": ["cash", "taxable", "traditional", "roth"],
    "traditional_first": ["cash", "traditional", "taxable", "roth"],
    "roth_first": ["cash", "roth", "taxable", "traditional"],
}

SERIES = [
    "wages", "other_income", "social_security", "tax_free_income", "asset_sale_proceeds",
    "contributions", "employer_match",
    "expenses_essential", "expenses_discretionary_planned", "expenses_discretionary",
    "debt_payments", "medicare_premiums", "spending_total",
    "rmd", "roth_conversion", "hsa_withdrawals",
    "withdrawals_cash", "withdrawals_taxable", "withdrawals_traditional", "withdrawals_roth",
    "withdrawals_total", "surplus_saved", "shortfall",
    "tax_federal_ordinary", "tax_federal_ltcg", "tax_niit", "tax_state", "tax_payroll", "tax_penalty",
    "tax_total",
    "agi", "taxable_ss", "deduction", "taxable_income", "ordinary_taxable_income", "marginal_rate",
    "realized_gains", "taxable_interest", "qualified_dividends",
    "balance_cash", "balance_taxable", "balance_traditional", "balance_roth", "balance_hsa",
    "portfolio", "other_assets", "liabilities", "net_worth",
    "spending_multiplier", "withdrawal_rate", "portfolio_return",
]


@dataclass
class SimResult:
    plan_hash: str
    years: Array                      # [T]
    price_index: Array                # [T] cumulative inflation, 1.0 in the start year
    series: dict[str, Array]          # name -> [P, T], nominal dollars
    account_ids: list[str]
    account_names: list[str]
    account_tax_types: list[str]
    account_balances: Array           # [P, T, A] end-of-year balances
    ages: dict[str, list[int | None]]  # member id -> age each year (None once deceased)
    filing_status: list[str]          # [T]
    rule_versions: list[str]          # [T]
    warnings: list[str] = field(default_factory=list)

    @property
    def n_paths(self) -> int:
        return self.account_balances.shape[0]

    def real(self, name: str) -> Array:
        """A series in start-year (inflation-adjusted) dollars."""
        return self.series[name] / self.price_index[None, :]


# --------------------------------------------------------------------------- helpers


def expected_returns(plan: PlanInput, n_years: int) -> Array:
    mu = np.array([c.expected_return for c in plan.asset_classes], dtype=float)
    return np.broadcast_to(mu, (1, n_years, len(mu))).copy()


def _amortize_year(balance: float, annual_rate: float, monthly_payment: float) -> tuple[float, float]:
    """Run 12 monthly payments. Returns (total paid this year, year-end balance)."""
    paid = 0.0
    r = annual_rate / 12.0
    for _ in range(12):
        if balance <= 0:
            break
        balance = balance * (1.0 + r)
        pay = min(monthly_payment, balance)
        balance -= pay
        paid += pay
    return paid, max(balance, 0.0)


def _rule_for_year(plan: PlanInput, year: int) -> TaxRuleSet:
    if plan.assumptions.tax_rule_year is not None:
        return load_rules(plan.assumptions.tax_rule_year)
    years = available_years()
    eligible = [y for y in years if y <= year]
    return load_rules(eligible[-1] if eligible else years[0])


class _Index:
    """Cumulative price level, valid both inside and outside the plan horizon."""

    def __init__(self, start_year: int, rates: Array, base_rate: float):
        self.start_year = start_year
        self.base_rate = base_rate
        self.level = np.concatenate([[1.0], np.cumprod(1.0 + rates)])  # level[t] for start_year + t

    def at(self, year: int) -> float:
        t = year - self.start_year
        if t < 0:
            return float((1.0 + self.base_rate) ** t)
        if t >= len(self.level):
            return float(self.level[-1] * (1.0 + self.base_rate) ** (t - len(self.level) + 1))
        return float(self.level[t])

    def ratio(self, from_year: int, to_year: int) -> float:
        return self.at(to_year) / self.at(from_year)


def _prepare_accounts(plan: PlanInput) -> tuple[list[Account], dict[int, int], int]:
    """Return the working account list, the traditional->Roth conversion map and
    the index of the account that receives reinvested surplus cash."""
    accounts = [a.model_copy(deep=True) for a in plan.accounts]
    conv_map: dict[int, int] = {}
    if plan.assumptions.roth_conversion.mode != "none":
        for i, a in enumerate(list(accounts)):
            if a.tax_type != "traditional":
                continue
            dest = next((j for j, b in enumerate(accounts) if b.tax_type == "roth" and b.owner == a.owner), None)
            if dest is None:
                accounts.append(Account(
                    id=f"roth_conversions_{a.owner}", name="Roth IRA (from conversions)", owner=a.owner,
                    tax_type="roth", balance=0.0, allocation=dict(a.allocation), annual_fee=a.annual_fee,
                ))
                dest = len(accounts) - 1
            conv_map[i] = dest
    surplus = next((i for i, a in enumerate(accounts) if a.tax_type == "taxable" and a.owner == JOINT), None)
    if surplus is None:
        surplus = next((i for i, a in enumerate(accounts) if a.tax_type == "taxable"), None)
    if surplus is None:
        surplus = next((i for i, a in enumerate(accounts) if a.tax_type == "cash"), None)
    if surplus is None:
        keys = [c.key for c in plan.asset_classes]
        key = "cash" if "cash" in keys else keys[0]
        accounts.append(Account(id="surplus_savings", name="Savings (unspent income)", owner=JOINT,
                                tax_type="taxable", balance=0.0, allocation={key: 1.0}))
        surplus = len(accounts) - 1
    return accounts, conv_map, surplus


def find_root(fn, lo: Array, hi: Array, f_lo: Array, f_hi: Array, *, xtol: float, ftol: float,
              max_iter: int) -> Array:
    """Vectorised bracketed root search for an increasing function.

    Each entry needs f(lo) < 0 <= f(hi), or lo == hi (already decided). Steps
    alternate between false position (exact on straight-line segments, which is
    what tax functions are made of) and bisection (guaranteed halving).
    Returns x where |f(x)| <= ftol or the bracket is narrower than xtol.
    """
    lo, hi, f_lo, f_hi = lo.copy(), hi.copy(), f_lo.copy(), f_hi.copy()
    for it in range(max_iter):
        width = hi - lo
        if float(np.max(width)) <= xtol:
            break
        if it % 2 == 0:
            denom = f_hi - f_lo
            ok = (denom > 0) & (width > 0)
            x = np.where(ok, lo - f_lo * width / np.where(ok, denom, 1.0), 0.5 * (lo + hi))
            x = np.clip(x, lo, hi)
        else:
            x = 0.5 * (lo + hi)
        fx = fn(x)
        neg = fx < 0
        done = np.abs(fx) <= ftol
        lo = np.where(neg | done, x, lo)
        f_lo = np.where(neg, fx, f_lo)
        hi = np.where(~neg | done, x, hi)
        f_hi = np.where(~neg, fx, f_hi)
    return hi


# --------------------------------------------------------------------------- main


def simulate(plan: PlanInput, returns: Array | None = None, inflation: Array | None = None) -> SimResult:
    """Simulate the plan.

    returns:   [P, T, C] annual returns per path, year and asset class. Defaults to
               one path of expected returns (the deterministic projection).
    inflation: [T] inflation during each year. Defaults to the plan assumption.
    """
    a = plan.assumptions
    years = np.arange(plan.start_year, plan.end_year + 1)
    T = len(years)
    C = len(plan.asset_classes)
    if returns is None:
        returns = expected_returns(plan, T)
    returns = np.asarray(returns, dtype=float)
    if returns.ndim != 3 or returns.shape[1] != T or returns.shape[2] != C:
        raise ValueError(f"returns must have shape [paths, {T}, {C}], got {returns.shape}")
    P = returns.shape[0]
    infl = np.full(T, a.inflation) if inflation is None else np.asarray(inflation, dtype=float)
    if infl.shape != (T,):
        raise ValueError(f"inflation must have shape [{T}]")

    price = _Index(plan.start_year, infl, a.inflation)
    health = _Index(plan.start_year, infl + (a.healthcare_inflation - a.inflation), a.healthcare_inflation)
    cola_rates = infl if a.ss_cola is None else np.full(T, a.ss_cola)
    cola = _Index(plan.start_year, cola_rates, a.inflation if a.ss_cola is None else a.ss_cola)

    warnings: list[str] = []
    members = plan.members
    M = len(members)
    mid = {m.id: i for i, m in enumerate(members)}
    first_death_year = min(m.death_year for m in members) if M == 2 else None

    accounts, conv_map, surplus_idx = _prepare_accounts(plan)
    A = len(accounts)
    ckey = {c.key: i for i, c in enumerate(plan.asset_classes)}
    W = np.zeros((A, C))
    for i, acct in enumerate(accounts):
        for k, w in acct.allocation.items():
            W[i, ckey[k]] = w
    fees = np.array([acct.annual_fee for acct in accounts])
    yields = np.array([c.income_yield for c in plan.asset_classes])
    qual = np.array([c.qualified_ratio for c in plan.asset_classes])
    types = [acct.tax_type for acct in accounts]
    is_taxlike = np.array([t in ("cash", "taxable") for t in types], dtype=float)
    is_trad = np.array([t == "traditional" for t in types], dtype=float)
    is_hsa = np.array([t == "hsa" for t in types], dtype=float)
    y_ord = (W * (yields * (1 - qual))).sum(axis=1) * is_taxlike
    y_q = (W * (yields * qual)).sum(axis=1) * is_taxlike
    type_masks = {t: np.array([x == t for x in types], dtype=float) for t in ("cash", "taxable", "traditional", "roth", "hsa")}

    bal = np.tile(np.array([acct.balance for acct in accounts], dtype=float), (P, 1))
    basis = np.tile(
        np.array([(acct.cost_basis if acct.cost_basis is not None else acct.balance) if types[i] in ("cash", "taxable")
                  else 0.0 for i, acct in enumerate(accounts)], dtype=float), (P, 1))

    strategy = a.withdrawal_strategy
    if strategy == "proportional":
        order: list[int] = []
    else:
        order = [i for t in WITHDRAWAL_ORDER[strategy] for i, x in enumerate(types) if x == t]
    spendable = 1.0 - is_hsa  # HSA money is only used for healthcare costs

    # Social Security building blocks (annual, start-year dollars)
    own_base, pia, claim_year, sp_factor = [], [], [], []
    for m in members:
        s = m.social_security
        months = s.claim_age * 12 + s.claim_months
        factor = ssmod.claim_factor(m.birth_year, months)
        annual = 12.0 * s.monthly_benefit
        if s.basis == "at_fra":
            own_base.append(annual * factor)
            pia.append(annual)
        else:
            own_base.append(annual)
            pia.append(annual / factor if factor > 0 else annual)
        claim_year.append(m.birth_year + s.claim_age)
        sp_factor.append(ssmod.spousal_factor(m.birth_year, months))

    # Liabilities and illiquid assets are deterministic
    liab_bal = {lb.id: lb.balance for lb in plan.liabilities}
    asset_sold: set[str] = set()

    out = {name: np.zeros((P, T)) for name in SERIES}
    acct_out = np.zeros((P, T, A))
    ages_out: dict[str, list[int | None]] = {m.id: [] for m in members}
    status_out: list[str] = []
    rule_out: list[str] = []
    magi_hist: list[Array] = []

    gr = a.guardrails
    mult = np.ones(P)
    init_rate = np.full(P, np.nan)
    guard_start = max(m.retirement_year for m in members)

    rc = a.roth_conversion
    if a.model_medicare_premiums and a.prior_magi is None:
        if any(plan.start_year + t - m.birth_year >= 65 for m in members for t in (0, 1)):
            warnings.append(
                "Medicare income surcharges (IRMAA) for the first two plan years assume standard premiums, "
                "because income for the two years before the plan was not provided."
            )
    early_roth_warned = False

    for t, year in enumerate(years):
        year = int(year)
        idx = price.at(year)
        alive = [m.birth_year <= year <= m.death_year for m in members]
        age = [year - m.birth_year for m in members]
        for i, m in enumerate(members):
            ages_out[m.id].append(age[i] if alive[i] else None)
        if not any(alive):  # cannot happen (end_year = last death) but keep arrays consistent
            status_out.append("single")
            rule_out.append("")
            continue
        status = "mfj" if plan.filing_status == "mfj" and (first_death_year is None or year <= first_death_year) \
            else "single"
        status_out.append(status)
        after_first_death = first_death_year is not None and year > first_death_year
        rules = _rule_for_year(plan, year)
        top_from = rules.raw["medicare"]["irmaa_top_tier_indexed_from_year"]
        params: YearTaxParams = rules.params(
            year, status,
            index_factor=price.ratio(rules.tax_year, year),
            medical_index_factor=health.ratio(rules.tax_year, year),
            irmaa_top_factor=price.ratio(top_from - 1, year) if year >= top_from else 1.0,
        )
        rule_out.append(params.rule_version)
        n65 = sum(1 for i in range(M) if alive[i] and age[i] >= 65)

        def eff_owner(owner: str, _alive=alive) -> int | None:
            """Member index whose age governs an account (the survivor inherits)."""
            if owner == JOINT:
                return next((i for i in range(M) if _alive[i]), None)
            i = mid[owner]
            if _alive[i]:
                return i
            return next((j for j in range(M) if _alive[j]), None)

        # ---- income (deterministic across paths) --------------------------------
        wages = [0.0] * M
        ordinary_other = 0.0
        pension_like = 0.0
        tax_free = 0.0
        for inc in plan.incomes:
            if inc.start_year is not None and year < inc.start_year:
                continue
            if inc.end_year is not None and year > inc.end_year:
                continue
            share = 1.0
            if inc.owner == JOINT:
                pass
            elif not alive[mid[inc.owner]]:
                if inc.survivor_pct <= 0:
                    continue
                share = inc.survivor_pct
            if inc.growth_mode == "inflation":
                g = idx * (1.0 + inc.growth_rate) ** t
            elif inc.growth_mode == "fixed":
                g = (1.0 + inc.growth_rate) ** t
            else:
                g = 1.0
            amount = inc.amount * g * share
            if inc.tax_treatment == "earned" and inc.owner != JOINT and alive[mid[inc.owner]]:
                wages[mid[inc.owner]] += amount
            elif inc.tax_treatment == "tax_free":
                tax_free += amount
            else:
                ordinary_other += amount
                if inc.kind in ("pension", "annuity"):
                    pension_like += amount

        # ---- Social Security ---------------------------------------------------
        ss_by_member = [0.0] * M
        for i in range(M):
            if not alive[i]:
                continue
            claimed = year >= claim_year[i]
            benefit = own_base[i] if claimed else 0.0
            if M == 2:
                j = 1 - i
                if alive[j]:
                    if a.spousal_benefits and claimed and year >= claim_year[j]:
                        benefit = max(benefit, 0.5 * pia[j] * sp_factor[i])
                elif claimed:
                    deceased = own_base[j] if members[j].death_year >= claim_year[j] else pia[j]
                    benefit = max(benefit, deceased)
            ss_by_member[i] = benefit * cola.at(year)
            if a.ss_reduction_year is not None and year >= a.ss_reduction_year:
                ss_by_member[i] *= 1.0 - a.ss_reduction_pct
        ss_total = sum(ss_by_member)

        # ---- contributions -------------------------------------------------------
        contrib = np.zeros(A)
        match = np.zeros(A)
        pretax = [0.0] * M
        for i, acct in enumerate(accounts):
            if acct.annual_contribution <= 0 and acct.employer_match <= 0:
                continue
            if acct.owner == JOINT:
                working = [k for k in range(M) if alive[k] and year < members[k].retirement_year]
                if not working:
                    continue
                k = working[0]
            else:
                k = mid[acct.owner]
                if not (alive[k] and year < members[k].retirement_year):
                    continue
            g = idx * (1.0 + acct.contribution_real_growth) ** t
            amount = acct.annual_contribution * g
            if acct.tax_type in ("traditional", "hsa"):
                amount = min(amount, max(wages[k] - pretax[k], 0.0))  # pre-tax money must come from pay
                pretax[k] += amount
            contrib[i] = amount
            match[i] = acct.employer_match * g
        contrib_total = float(contrib.sum())

        # ---- illiquid assets: sales ---------------------------------------------
        sale_proceeds = 0.0
        sale_gain = 0.0
        for asset in plan.assets:
            if asset.id in asset_sold or asset.sale_year is None or year < asset.sale_year:
                continue
            value = asset.value * (1.0 + asset.growth_rate) ** t
            net = value * (1.0 - asset.sale_cost_pct)
            gain = max(net - asset.cost_basis, 0.0)
            if asset.primary_residence:
                gain = max(gain - params.home_sale_exclusion, 0.0)
            payoff = 0.0
            for lb in plan.liabilities:
                if lb.linked_asset_id == asset.id:
                    payoff += liab_bal[lb.id]
                    liab_bal[lb.id] = 0.0
            sale_proceeds += net - payoff
            sale_gain += gain
            asset_sold.add(asset.id)

        # ---- debt payments ---------------------------------------------------------
        debt_paid = 0.0
        for lb in plan.liabilities:
            paid, liab_bal[lb.id] = _amortize_year(liab_bal[lb.id], lb.interest_rate, lb.monthly_payment)
            debt_paid += paid

        # ---- expenses --------------------------------------------------------------
        essential = 0.0
        discretionary = 0.0
        health_exp = 0.0
        one_time = 0.0
        for e in plan.expenses:
            if e.start_year is not None and year < e.start_year:
                continue
            if e.end_year is not None and year > e.end_year:
                continue
            if e.inflation_mode == "general":
                g = idx
            elif e.inflation_mode == "healthcare":
                g = health.at(year)
            elif e.inflation_mode == "custom":
                g = (1.0 + e.custom_rate) ** t
            else:
                g = 1.0
            amount = e.amount * g
            if after_first_death and e.kind != "one_time":
                amount *= a.survivor_expense_pct if e.survivor_pct is None else e.survivor_pct
            if e.category == "essential":
                essential += amount
            else:
                discretionary += amount
            if e.kind == "healthcare":
                health_exp += amount
            if e.kind == "one_time":
                one_time += amount

        # ---- Medicare premiums (IRMAA uses income from two years earlier) -------------
        medicare = np.zeros(P)
        n_medicare = sum(1 for i in range(M) if alive[i] and age[i] >= params.medicare_age)
        if a.model_medicare_premiums and n_medicare:
            if t >= 2:
                look = magi_hist[t - 2]
            elif a.prior_magi is not None and len(a.prior_magi) == 2:
                look = np.full(P, float(a.prior_magi[t]))
            else:
                look = np.zeros(P)
            ib, idd = irmaa_monthly(params, look)
            medicare = n_medicare * 12.0 * (params.part_b_monthly + ib + idd)

        # ---- payroll tax, required distributions ------------------------------------
        fica = float(payroll_tax(params, [np.array([w]) for w in wages])[0]) if any(wages) else 0.0
        rmd_a = np.zeros((P, A))
        penal = np.zeros(A)
        for i, acct in enumerate(accounts):
            if types[i] != "traditional":
                continue
            k = eff_owner(acct.owner)
            if k is None:
                continue
            rmd_a[:, i] = bal[:, i] * rmd_fraction(age[k], members[k].birth_year)
            if age[k] < PENALTY_AGE:
                penal[i] = 1.0
        rmd_total = rmd_a.sum(axis=1)

        roth_young = np.zeros(A)
        for i, acct in enumerate(accounts):
            k = eff_owner(acct.owner)
            if types[i] == "roth" and k is not None and age[k] < PENALTY_AGE:
                roth_young[i] = 1.0

        # ---- guardrails ----------------------------------------------------------------
        portfolio_start = bal.sum(axis=1)
        gross_income = sum(wages) + ordinary_other + tax_free + ss_total
        rate_now = np.zeros(P)
        if year >= guard_start:
            base_spend = essential + debt_paid + medicare - one_time
            with np.errstate(divide="ignore", invalid="ignore"):
                def draw_rate(m_: Array) -> Array:
                    need = np.clip(base_spend + discretionary * m_ - gross_income, 0.0, None)
                    return np.where(portfolio_start > 0, need / np.where(portfolio_start > 0, portfolio_start, 1.0),
                                    np.where(need > 0, np.inf, 0.0))
                rate_now = draw_rate(mult)
                if gr.enabled:
                    unset = np.isnan(init_rate) & (rate_now > 0) & np.isfinite(rate_now)
                    was_set = ~np.isnan(init_rate)
                    init_rate = np.where(unset, rate_now, init_rate)
                    cut = was_set & (rate_now > init_rate * (1.0 + gr.upper_band))
                    lift = was_set & (rate_now < init_rate * (1.0 - gr.lower_band))
                    mult = np.where(cut, np.maximum(gr.min_multiplier, mult * (1.0 - gr.cut_pct)), mult)
                    mult = np.where(lift, np.minimum(gr.max_multiplier, mult * (1.0 + gr.raise_pct)), mult)
                    rate_now = draw_rate(mult)

        disc_actual_plan = discretionary * mult
        spending = essential + debt_paid + medicare + disc_actual_plan

        # ---- HSA pays healthcare costs tax-free -----------------------------------------
        hsa_w = np.zeros((P, A))
        if is_hsa.any():
            remaining = health_exp + medicare
            for i in range(A):
                if types[i] != "hsa":
                    continue
                k = eff_owner(accounts[i].owner)
                if k is None or year < members[k].retirement_year:
                    continue
                take = np.minimum(bal[:, i], remaining)
                hsa_w[:, i] = take
                remaining = remaining - take
        hsa_total = hsa_w.sum(axis=1)

        # ---- solve for the withdrawals that fund spending and taxes ----------------------
        taxable_wages = sum(wages) - sum(pretax)
        cash_in = (sum(wages) - contrib_total - fica + ordinary_other + tax_free + ss_total
                   + sale_proceeds + rmd_total + hsa_total)
        ordinary_base = taxable_wages + ordinary_other + rmd_total
        after_forced = bal - rmd_a - hsa_w
        trad_room = (after_forced * is_trad)
        trad_room_total = trad_room.sum(axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            gain_frac = np.where(bal > 0, np.clip(1.0 - basis / np.where(bal > 0, bal, 1.0), 0.0, 1.0), 0.0) * is_taxlike

        def allocate(G: Array, avail: Array) -> Array:
            if strategy == "proportional":
                pool = avail * spendable
                total = pool.sum(axis=1)
                frac = np.where(total > 0, np.minimum(G / np.where(total > 0, total, 1.0), 1.0), 0.0)
                return pool * frac[:, None]
            w = np.zeros_like(avail)
            remaining = G.copy()
            for i in order:
                take = np.minimum(remaining, avail[:, i])
                w[:, i] = take
                remaining = remaining - take
            return w

        def evaluate(G: Array, avail: Array, conv: Array):
            w = allocate(G, avail)
            trad_w = (w * is_trad).sum(axis=1)
            gains = (w * gain_frac).sum(axis=1)
            left = avail - w
            interest = (left * y_ord).sum(axis=1)
            qdiv = (left * y_q).sum(axis=1)
            penalty = params.penalty_rate * (w * penal).sum(axis=1)
            fed = federal_income_tax(
                params,
                ordinary_income=ordinary_base + conv + trad_w + interest,
                qualified_dividends=qdiv,
                long_term_gains=gains + sale_gain,
                ss_benefits=np.full(P, ss_total),
                net_investment_income=interest + qdiv + gains + sale_gain,
                n_age_65=n65,
            )
            st = state_income_tax(
                rate=a.state_tax.rate, agi=fed.agi, taxable_ss=fed.taxable_ss,
                retirement_income=pension_like + rmd_total + trad_w + conv,
                taxes_social_security=a.state_tax.taxes_social_security,
                exempts_retirement_income=a.state_tax.exempts_retirement_income,
            )
            tax = fed.total + st + penalty
            net = cash_in + G - tax - spending
            return net, w, fed, st, penalty, gains, interest, qdiv

        def solve(conv: Array):
            with np.errstate(divide="ignore", invalid="ignore"):
                frac = np.where(trad_room_total > 0, conv / np.where(trad_room_total > 0, trad_room_total, 1.0), 0.0)
            conv_a = trad_room * frac[:, None]
            avail = after_forced - conv_a
            g_max = (avail * spendable).sum(axis=1)
            lo = np.zeros(P)
            hi = g_max.copy()
            net0 = evaluate(lo, avail, conv)[0]
            net_max = evaluate(hi, avail, conv)[0]
            hi = np.where(net0 >= 0, 0.0, hi)          # no withdrawal needed
            lo = np.where(net_max < 0, g_max, lo)      # not enough money: withdraw everything
            G = find_root(lambda g: evaluate(g, avail, conv)[0], lo, hi, net0, net_max,
                          xtol=CASH_TOLERANCE / 10, ftol=CASH_TOLERANCE, max_iter=SOLVER_MAX_ITER)
            return (G, conv_a, avail) + evaluate(G, avail, conv)

        conv = np.zeros(P)
        conv_active = (rc.mode != "none"
                       and (rc.start_year is None or year >= rc.start_year)
                       and (rc.end_year is None or year <= rc.end_year)
                       and bool((trad_room_total > 0).any()))
        if conv_active and rc.mode == "fixed":
            conv = np.minimum(rc.amount * idx, trad_room_total)
        elif conv_active:
            if rc.mode == "fill_bracket":
                target = params.bracket_top(rc.bracket_rate)
            else:
                target = rc.amount * idx

            def metric(c: Array) -> Array:
                res = solve(c)
                fed_ = res[5]
                return fed_.ordinary_taxable_income if rc.mode == "fill_bracket" else fed_.agi

            if np.isfinite(target):
                # The metric rises with the conversion, so the amount that lands on
                # the target is a bracketed root.
                lo_c = np.zeros(P)
                hi_c = trad_room_total.copy()
                d_lo = metric(lo_c) - target
                d_hi = metric(hi_c) - target
                hi_c = np.where(d_lo >= 0, 0.0, hi_c)      # already at/above the target: convert nothing
                lo_c = np.where(d_hi <= 0, hi_c, lo_c)     # converting everything still stays below
                conv = find_root(lambda c: metric(c) - target, lo_c, hi_c, d_lo, d_hi,
                                 xtol=CONVERSION_TOLERANCE / 10, ftol=CONVERSION_TOLERANCE,
                                 max_iter=SOLVER_MAX_ITER)
            else:
                conv = trad_room_total.copy()

        G, conv_a, avail, net, w, fed, st, penalty, gains, interest, qdiv = solve(conv)
        if not early_roth_warned and float((w * roth_young).sum()) > 0:
            warnings.append(
                "Roth money is withdrawn before age 59 1/2 in some years. It is treated as tax-free; tax and "
                "penalties on early withdrawal of Roth earnings are not modelled."
            )
            early_roth_warned = True
        shortfall = np.clip(-net, 0.0, None)
        shortfall = np.where(shortfall < 0.01, 0.0, shortfall)
        surplus = np.clip(net, 0.0, None)

        # ---- apply flows -------------------------------------------------------------------
        with np.errstate(divide="ignore", invalid="ignore"):
            keep = np.where(bal > 0, (avail - w) / np.where(bal > 0, bal, 1.0), 1.0)
        new_bal = avail - w
        basis = basis * np.clip(keep, 0.0, 1.0) * is_taxlike
        basis = basis + new_bal * (y_ord + y_q)          # reinvested, already-taxed income
        for src, dest in conv_map.items():
            new_bal[:, dest] += conv_a[:, src]
        new_bal[:, surplus_idx] += surplus
        basis[:, surplus_idx] += surplus
        new_bal = new_bal + contrib + match
        basis = basis + (contrib + match) * is_taxlike
        acct_ret = np.clip(returns[:, t, :] @ W.T - fees, -1.0, None)
        before_growth = new_bal
        bal = new_bal * (1.0 + acct_ret)

        # ---- record ---------------------------------------------------------------------------
        magi_hist.append(fed.agi.copy())
        other_assets = 0.0
        for asset in plan.assets:
            if asset.id not in asset_sold:
                other_assets += asset.value * (1.0 + asset.growth_rate) ** (t + 1)
        liabilities = sum(liab_bal.values())
        spent_disc = np.clip(disc_actual_plan - shortfall, 0.0, None)
        o = out
        o["wages"][:, t] = sum(wages)
        o["other_income"][:, t] = ordinary_other
        o["social_security"][:, t] = ss_total
        o["tax_free_income"][:, t] = tax_free
        o["asset_sale_proceeds"][:, t] = sale_proceeds
        o["contributions"][:, t] = contrib_total
        o["employer_match"][:, t] = float(match.sum())
        o["expenses_essential"][:, t] = essential
        o["expenses_discretionary_planned"][:, t] = discretionary
        o["expenses_discretionary"][:, t] = spent_disc
        o["debt_payments"][:, t] = debt_paid
        o["medicare_premiums"][:, t] = medicare
        o["spending_total"][:, t] = spending - shortfall
        o["rmd"][:, t] = rmd_total
        o["roth_conversion"][:, t] = conv
        o["hsa_withdrawals"][:, t] = hsa_total
        for tname in ("cash", "taxable", "traditional", "roth"):
            o[f"withdrawals_{tname}"][:, t] = (w * type_masks[tname]).sum(axis=1)
        o["withdrawals_traditional"][:, t] += rmd_total
        o["withdrawals_total"][:, t] = G + rmd_total + hsa_total
        o["surplus_saved"][:, t] = surplus
        o["shortfall"][:, t] = shortfall
        o["tax_federal_ordinary"][:, t] = fed.ordinary_tax
        o["tax_federal_ltcg"][:, t] = fed.ltcg_tax
        o["tax_niit"][:, t] = fed.niit
        o["tax_state"][:, t] = st
        o["tax_payroll"][:, t] = fica
        o["tax_penalty"][:, t] = penalty
        o["tax_total"][:, t] = fed.total + st + penalty + fica
        o["agi"][:, t] = fed.agi
        o["taxable_ss"][:, t] = fed.taxable_ss
        o["deduction"][:, t] = fed.deduction
        o["taxable_income"][:, t] = fed.taxable_income
        o["ordinary_taxable_income"][:, t] = fed.ordinary_taxable_income
        o["marginal_rate"][:, t] = fed.marginal_rate
        o["realized_gains"][:, t] = gains + sale_gain
        o["taxable_interest"][:, t] = interest
        o["qualified_dividends"][:, t] = qdiv
        for tname in ("cash", "taxable", "traditional", "roth", "hsa"):
            o[f"balance_{tname}"][:, t] = (bal * type_masks[tname]).sum(axis=1)
        portfolio = bal.sum(axis=1)
        o["portfolio"][:, t] = portfolio
        o["other_assets"][:, t] = other_assets
        o["liabilities"][:, t] = liabilities
        o["net_worth"][:, t] = portfolio + other_assets - liabilities
        o["spending_multiplier"][:, t] = mult
        o["withdrawal_rate"][:, t] = np.where(np.isfinite(rate_now), rate_now, 0.0)
        start_total = before_growth.sum(axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            o["portfolio_return"][:, t] = np.where(start_total > 0, portfolio / np.where(start_total > 0, start_total, 1.0) - 1.0, 0.0)
        acct_out[:, t, :] = bal

    return SimResult(
        plan_hash=plan.content_hash(),
        years=years,
        price_index=price.level[:T].copy(),
        series=out,
        account_ids=[x.id for x in accounts],
        account_names=[x.name for x in accounts],
        account_tax_types=types,
        account_balances=acct_out,
        ages=ages_out,
        filing_status=status_out,
        rule_versions=rule_out,
        warnings=warnings,
    )
