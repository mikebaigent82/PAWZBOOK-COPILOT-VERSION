# Architecture

## Principle

**The calculation engine is the only source of numbers.** It is plain, tested Python with no database, clock or network access. The same inputs and seed always produce the same output. The API stores results together with the exact inputs they came from. The web app and the AI assistant only display and explain those results.

```
 Browser (Next.js)  ──/api──▶  FastAPI  ──▶  plan_builder  ──▶  engine (pure Python/NumPy)
        ▲                         │                                   │
        └──── JSON results ◀──────┴── PostgreSQL (data, snapshots, ◀──┘
                                       results, audit log)
 Assistant: FastAPI ──tools──▶ engine      (an LLM, if enabled, sees tool results only)
```

## Layout

```
backend/
  app/engine/          calculation engine (no I/O except reading its own data files)
    data/              versioned tax rules, IRS RMD table, historical stress data
    models.py          PlanInput: the complete, validated input to every calculation
    taxrules.py        loads a tax-rule version and indexes it for later years
    tax.py             federal / payroll / state tax, Social Security taxation, IRMAA
    rmd.py             required minimum distributions
    social_security.py claiming adjustments, spousal and survivor rules
    simulate.py        the year-by-year simulation (shared by projection and Monte Carlo)
    projection.py      deterministic projection and summaries
    montecarlo.py      correlated random returns, percentiles, success rates
    roth.py            Roth conversion and withdrawal-order comparison
    stress.py          historical, custom and sequence-of-returns tests
    lookthrough.py     portfolio mix, look-through and concentration
  app/models.py        database schema (SQLAlchemy); alembic/ holds migrations
  app/services/        plan_builder (DB → PlanInput), runs (store results), reports, CSV import, insights
  app/api/             HTTP routes: auth, data, planning, misc (reports, assistant, privacy)
  app/ai/              assistant: tool definitions + live (LLM) and built-in modes
  app/providers/       swappable integrations: LLM client, account aggregation
  app/security/        password hashing, sessions, TOTP, encryption, rate limiting
  tests/               engine benchmarks and end-to-end API tests
frontend/
  src/app/<page>/      one folder per screen
  src/components/      shared UI, charts, forms, session/shell
  src/lib/             API client, formatting, types
deploy/                environment templates and backup script
docker-compose.yml     db + api + web + daily backups
```

## Database

All tables listed in the specification exist: Users, Households, Members, Accounts, Holdings, Securities, Prices, AssetClasses, Allocations, Transactions, IncomeSources, Expenses, Liabilities, RealEstate, Businesses, Pensions, SSEstimates, TaxRuleVersions, Plans, Assumptions, Scenarios, ProjectionResults, MonteCarloRuns, RothStrategies, Reports, AIConversations and AuditLogs. Supporting tables: sessions, household_access, ai_messages, ai_proposals.

- **User isolation.** Every household row carries `household_id`. Every route resolves the caller's household from their session (via `household_access`), and `Ctx.owned()` refuses any id from another household with a 404. Cross-household access is covered by tests.
- **Reproducibility.** Assumptions are versioned: a change adds a row and never overwrites one. Each projection, Monte Carlo run and Roth comparison stores its full `input_snapshot`, a SHA-256 `input_hash`, the engine version and the assumption version. Monte Carlo runs also store the seed, path count, distribution and NumPy version.
- **Timestamps.** Every table has `created_at` and `updated_at`.
- **Advisor-ready.** `household_access` (owner / editor / viewer) already lets one user open several households, and `X-Household-Id` selects which one. An advisor UI can be added without schema changes.

## Security and privacy

| Area | What is done |
|---|---|
| Passwords | Argon2id hashing, minimum 10 characters, generic login errors, account lockout after repeated failures |
| Sessions | Random tokens; only a keyed HMAC is stored. HttpOnly, SameSite=Lax cookies, Secure outside development. Session expiry. Changing the password signs out other sessions |
| CSRF | Double-submit token required on every state-changing request |
| MFA | TOTP (authenticator apps) with 8 single-use recovery codes. The TOTP secret is encrypted at rest (Fernet) |
| Rate limiting | Per-IP limits on sign-in routes and on the API as a whole (in-process; use the reverse proxy for multi-instance deployments) |
| Transport | Run behind HTTPS. HSTS is sent outside development. Security headers on every response |
| Secrets | From the environment only. Production refuses to start with development keys |
| Audit | Sign-ins, changes, calculations, exports, AI consent and proposals are logged. Users can see their own activity |
| Privacy rights | Full JSON export of everything stored. Permanent account deletion (cascades through all household data) |
| AI | Off by default (built-in helper, no data leaves the server). Live mode requires both an operator flag confirming a data-processing agreement and per-user consent, which is recorded and can be withdrawn. Tool results exclude email, account names and institution names. The model can only call tools; plan changes become proposals that the user must confirm |
| Bank data | Never handles bank credentials; the provider abstraction uses hosted link tokens. No invented balances: without credentials, linking simply reports "not connected" |

Encryption at rest for the whole database should be provided by the host (encrypted volume or managed Postgres). Field-level encryption is used for the MFA secret.

## Key decisions

- **Shared simulation core.** The deterministic projection is a one-path Monte Carlo using expected returns, so both always apply identical rules.
- **Vectorised solving.** Withdrawals needed to cover spending and taxes are found per year with a bracketed root search (false position + bisection) across all paths at once, to within half a cent. A full 1,000-path, 35-year run takes about 0.3 s, or about 1.2 s with bracket-filling Roth conversions.
- **Next.js rewrites** proxy `/api` to the backend, so cookies stay first-party and no CORS is needed in production.
- **Recharts** is used for all charts. Every chart states its dollar basis and assumptions.
