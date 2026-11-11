# Calculations: methods, sources and limitations

Everything here is implemented in `backend/app/engine` and covered by `backend/tests`. Expected values in the tests were worked out by hand from the published rules, independently of the code, and the arithmetic is shown in the test comments.

## Conventions

- **Timing.** Every year: (1) start-of-year balances; (2) income, contributions, required distributions, Roth conversions and the withdrawals needed for spending and taxes all happen; (3) the remaining balance earns the year's return, net of fees. Taxes for a year are paid in that year.
- **Dollars.** The engine works in nominal (future) dollars. `price_index` (cumulative inflation, 1.0 in the start year) converts to start-year ("today's") dollars. The UI always labels which one it shows.
- **Inputs.** All amounts are entered in start-year dollars. Incomes and expenses grow with general inflation, healthcare inflation, a fixed rate, or not at all, as chosen.
- **Determinism.** The same `PlanInput` (fingerprinted by SHA-256 of its canonical JSON) and seed always produce the same numbers.

## Federal tax (`tax.py`, `taxrules.py`)

- **Rule versions:** `data/tax_rules_2025.json` (Rev. Proc. 2024-40 plus OBBBA) and `data/tax_rules_2026.json` (Rev. Proc. 2025-32). Each plan year uses the newest version not later than that year. Later years index the inflation-adjusted amounts by the plan's inflation assumption. Amounts that are fixed in law are not indexed: the Social Security taxation bases, the NIIT and additional-Medicare thresholds, the senior deduction, the home-sale exclusion and the frozen top IRMAA tier.
- **Ordinary income** uses the bracket schedules. **Qualified dividends and long-term gains** are stacked on top of ordinary income in the 0/15/20% bands. **NIIT** is 3.8% of the lesser of net investment income and AGI above the threshold.
- **Social Security taxation** follows the IRC §86 / Pub. 915 worksheet: provisional income, 50% and 85% tiers.
- **Deductions:** the standard deduction, plus the age-65 additional amount, plus the OBBBA senior deduction ($6,000 per person aged 65+, reduced by 6% of AGI over $75k / $150k, for 2025-2028 only).
- **Payroll tax:** 6.2% Social Security up to the wage base (per person), 1.45% Medicare, and 0.9% additional Medicare above the threshold.
- **Early-withdrawal penalty:** 10% on pre-tax withdrawals before age 60. This is an integer-age stand-in for 59½.
- **Filing statuses:** single and married filing jointly. After the first spouse's death the survivor files as single from the following year.

**Limitations:** no itemized deductions, credits, AMT, qualified-widow(er) status, head of household, or Social Security earnings test. The tax tables are not used; the IRS schedules give results within a few dollars of them.

## State tax

A single effective rate chosen by the user, applied to federal AGI. Social Security and/or retirement income can be excluded with toggles. Built-in default: 0% for states without wage income tax, otherwise 4%. **This is a deliberate simplification, not a state bracket engine.**

## Medicare (IRMAA)

Part B standard premium plus income-related surcharges for Parts B and D, per person from age 65. The surcharge is based on MAGI from **two years earlier**: the plan's own AGI from year *t-2*, or the user-entered prior MAGI for the first two years. Premiums grow with healthcare inflation and thresholds with general inflation. The top tier is frozen until 2028. Surcharge tiers are cliffs: one dollar over a threshold triggers the whole surcharge.

## Required minimum distributions (`rmd.py`)

RMDs start at 72 (born ≤1950), 73 (1951-59) or 75 (1960+), per SECURE 2.0. The required amount is the prior year-end balance divided by the IRS Uniform Lifetime Table divisor (Pub. 590-B, Table III). Accounts pass to the surviving spouse. **Limitation:** the Joint Life table (spouse more than 10 years younger) is not used.

## Social Security (`social_security.py`)

- **Full retirement age** by birth year.
- **Early claiming:** −5/9% per month for the first 36 months, −5/12% per month after that.
- **Delayed claiming:** +2/3% per month up to age 70.
- **Spousal benefit:** up to 50% of the worker's full-retirement-age amount, reduced for early claiming (25/36% and 5/12% per month), with no delayed credits.
- **Survivor:** keeps the larger of the two benefits.
- **COLA** equals inflation unless overridden. An optional future cut (for example −20% from 2034) can be applied.

**Limitations:** benefits start in January of the claim year; no earnings test, family maximum, survivor early-claiming reduction or divorced-spouse rules.

## Withdrawals

Each year the engine finds the smallest withdrawal G at which **cash in − taxes − spending ≥ 0**. Taxes depend on G itself, because withdrawals create taxable income and gains. A vectorised bracketed root search solves for G to within $0.005. The order is configurable:

- savings → taxable → pre-tax → Roth (default);
- pre-tax first;
- Roth first;
- proportional across all accounts.

Taxable-account withdrawals realise gains pro rata to the unrealised gain. HSAs pay healthcare costs and Medicare premiums tax-free after retirement. Money left over after spending (for example, from RMDs) is reinvested in the taxable account with full cost basis. If every account is empty, the unpaid remainder is reported as a **shortfall**, and the year's spending is reduced by that amount.

## Roth conversions (`roth.py`)

The conversion modes are:

- a fixed amount per year;
- fill to the top of a chosen bracket;
- fill AGI to a ceiling (used for IRMAA thresholds).

Fill modes are solved exactly, to within $1, with the same root search. The **optimizer** runs the full projection for each candidate:

- no conversions;
- fill the 10/12/22/24/32% bracket over the "gap years" (retirement until RMDs start) or from now;
- stay under the first IRMAA threshold.

It scores each candidate on three objectives in today's dollars:

- **lifetime cost:** taxes plus Medicare premiums;
- **after-tax wealth:** pre-tax balances reduced by the household's own final-year marginal federal rate plus the state rate;
- **beneficiary value:** pre-tax and HSA balances reduced by the heirs' assumed tax rate.

Scores are min-max normalised and weighted by the user's goal. Pareto-efficient options are flagged. A strategy that creates or worsens a shortfall is never recommended. **Limitations:** the comparison uses expected returns rather than Monte Carlo, assumes today's tax law indexed for inflation, and does not model the 5-year rule on converted amounts.

## Monte Carlo (`montecarlo.py`)

Annual returns are r = μ + σ·x, where x has unit variance and the plan's correlation matrix, via the Cholesky factor. x can be:

- multivariate **normal**;
- **Student-t** (scaled to unit variance, with a shared χ² mixing variable, so bad years hit all assets together);
- symmetric **Laplace** (a normal variance-mixture with an Exp(1) mixing variable).

Returns are independent from year to year and floored at −100%. The random generator is NumPy PCG64(seed). The defaults are 1,000 paths and seed 20260101. A path **succeeds** when all planned spending (after guardrail adjustments) is paid in every year. "Essentials covered" counts paths in which unpaid spending never exceeds the planned discretionary amount. Tests check means, volatilities, correlations, kurtosis (normal ≈ 3, Laplace ≈ 6), reproducibility, and that zero volatility reproduces the deterministic projection exactly.

**Limitation:** inflation is deterministic in Monte Carlo (it can be stressed separately).

## Spending guardrails

These are Guyton-Klinger-style rules applied inside every path, from the year everyone is retired. The initial withdrawal rate is the first retirement year's net need divided by the portfolio. Each later year:

- if the current rate exceeds the initial rate × (1 + upper band), discretionary spending is cut by `cut_pct`;
- if it falls below the initial rate × (1 − lower band), discretionary spending is raised by `raise_pct`;
- spending is held between `min_multiplier` and `max_multiplier` of plan.

Essential spending is never changed. Defaults are 20% bands, 10% steps, and limits of 0-150%.

## Stress tests (`stress.py`)

- **Historical:** replays rounded annual returns for stocks, 10-year Treasuries and T-bills, plus CPI, for 1929-32, 1973-74, 2000-02, 2008 and 2022 (`data/historical_scenarios.json`). The replay starts in a chosen plan year, and other years use expected values. It is always labelled as historical data, never as a projection.
- **Custom:** a stock, bond or cash shock for N years, higher inflation, permanently lower returns, and/or a longer life.
- **Sequence:** returns of mean − k·σ for N years, then mean + k·σ for N years (or the reverse). The arithmetic average is unchanged; only the order differs.

## Portfolio analytics (`lookthrough.py`)

Holdings with composition data (asset-class, security and sector weights, each with a source and date) are split into their parts. Direct and through-fund exposure to the same security are combined. Holdings without composition data are counted as themselves and listed under "not covered". Flags are raised for any single security above 10%, the top five above 50%, or one non-cash asset class above 90%. A Herfindahl index is reported. Built-in compositions exist only at asset-class level for five broad index funds; this describes what they are designed to track, not live holdings.

## Other modules

- **Debts:** monthly amortisation (12 payments a year at rate/12). Payments count as spending until the debt is paid off. A mortgage linked to a property is repaid from the sale proceeds.
- **Property and business:** values grow at a fixed rate. A sale in a chosen year adds the proceeds minus selling costs, taxed as a long-term gain over the cost basis. The main-home exclusion is $250k single / $500k joint. Business income is ordinary income until the sale.
- **Pensions:** start at a chosen age, with an optional COLA and a survivor percentage.
- **After the first death:** recurring expenses drop to the survivor percentage (default 80%, adjustable per expense). Incomes owned by the deceased stop unless they have a survivor percentage.

## Default capital-market assumptions

Arithmetic nominal means: US stocks 7.0% (volatility 16%), international stocks 7.0% (18%), bonds 4.0% (6%), cash 3.0% (1%), real-estate funds 6.0% (17%), other 5.0% (15%). Correlations are in `models.default_correlations`. These are planning assumptions, not forecasts, and every value can be changed in Settings.
