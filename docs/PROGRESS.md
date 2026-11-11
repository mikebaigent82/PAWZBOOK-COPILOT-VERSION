# Progress log

Status against the nine phases in the specification.

| Phase | Status | Notes |
|---|---|---|
| 1. Architecture, schema, auth, shell | Done | FastAPI + PostgreSQL/Alembic; 31 tables; sessions, TOTP MFA, CSRF, rate limits; Next.js shell |
| 2. Accounts, holdings, income, expenses, net worth | Done | Manual entry and CSV import (accounts, holdings, transactions, expenses); property, business, debts, pensions |
| 3. Deterministic year-by-year engine | Done | Shared simulation core; cash-flow identity tested to the cent every year |
| 4. Investment analytics and look-through | Done | Asset-class, security and sector look-through; concentration flags; coverage reporting |
| 5. Monte Carlo and guardrails | Done | Correlated normal / Student-t / Laplace; seeded and stored; guardrails inside each path |
| 6. Tax engine and Roth optimizer | Done | 2025 and 2026 federal rule versions (OBBBA), NIIT, Social Security taxation, IRMAA, RMDs; three-objective optimizer |
| 7. Social Security, pensions, healthcare, real estate, stress tests, scenarios | Done | Spousal and survivor benefits; Medicare premiums; HSA; home sale with exclusion; historical, custom and sequence tests; scenarios that never touch the baseline |
| 8. AI assistant | Done | Tool-calling only; consent-gated live mode (OpenRouter/OpenAI-compatible); private built-in helper; proposals need confirmation |
| 9. Reports, security, performance, deployment | Done | PDF, Excel and CSV reports with assumptions and data freshness; Docker Compose with daily backups; staging/production env files |

## Tests

- `backend/tests/test_tax.py`: tax brackets, capital gains stacking, NIIT, Social Security taxation, senior deduction phase-out, payroll tax, IRMAA cliffs, indexing, RMD table, Social Security claiming factors (all against hand calculations or SSA/IRS published figures).
- `backend/tests/test_simulate.py`: compounding, fees, inflation, cash-flow identity, withdrawal order, RMDs, early-withdrawal penalty, cost basis, survivor rules, Roth conversion modes, debts, home sale, HSA, Medicare lookback, guardrails, determinism.
- `backend/tests/test_montecarlo.py`: return moments, correlations and fat tails; reproducibility; zero volatility matching the projection; guardrails raising success; the optimizer agreeing with direct projections; stress tests; look-through.
- `backend/tests/test_api.py`: sign-up, sign-in, lockout, rate limits, MFA and recovery codes, CSRF, cross-household isolation, every calculation route, scenarios, reports, assistant (built-in and scripted live mode, consent and data minimisation), export and deletion. Runs on SQLite and PostgreSQL.
- Browser walkthrough (Playwright, run during development): sign-up, guided setup, every page, what-if, stress test, assistant, year detail, PDF download, phone width with no horizontal scroll.

Totals at the time of writing: 120 backend tests passing; front end type-checks and builds.

## Open items and next steps

1. **Account linking.** The Plaid link-token call is in place; exchanging the public token and syncing balances and holdings still needs to be done (with credentials).
2. **State tax** is a single effective rate. A per-state bracket engine would improve accuracy for high-tax states.
3. **Monte Carlo inflation** is fixed; stochastic inflation correlated with returns would be a refinement.
4. **Joint Life RMD table** (spouse more than 10 years younger) and the Social Security earnings test are not modelled.
5. **Docker images** were defined but not built in the development environment (no Docker daemon was available). The backend package install and the Next.js standalone server were verified separately.
6. **Rate limiting** is per process. Put a limit at the reverse proxy if running several API instances.
7. **Advisor multi-client UI**: the data model supports it (`household_access`); screens are not built.
