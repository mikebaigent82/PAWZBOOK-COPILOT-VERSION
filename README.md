# Tallgrass Planner

![Home page with sample data](docs/screenshot-home.png)

A private retirement and wealth planner. It answers one question in plain English, **"Am I on track?"**, and lets you explore what would change the answer.

- Enter your savings, income and spending by hand (or import a spreadsheet file). No bank connection is needed.
- See a year-by-year plan, with taxes, Social Security, Medicare and required withdrawals worked out for you.
- Get a **chance of success**: your plan is tested in 1,000 possible futures, good and bad.
- Try **what-ifs** (retire later, spend less, claim Social Security at 70) without changing your saved plan.
- Compare **tax strategies** (Roth conversions, which accounts to spend first).
- Run **bad-market tests**, for example a repeat of the 2008 crash.
- **Ask questions** in everyday words. The assistant only reports numbers from the plan's own calculations, and it never changes anything unless you press Confirm.
- Download **reports** as PDF, Excel or CSV.

> Everything the app shows is an estimate based on what you enter and the assumptions in Settings. It is not a guarantee, and it is not financial, tax or legal advice.

---

## Using it (for the person doing the planning)

1. **Create an account** with your email and a password of at least 10 characters.
2. **Set up**: either enter your own details (about 10 minutes) or load the **sample data** to look around first. Sample data is clearly marked; clear it under *Settings → Your data*.
3. Helpful papers to have nearby:
   - your latest account statements (401(k), IRA, brokerage, bank);
   - your Social Security statement from **ssa.gov/myaccount** (use the amount "at full retirement age");
   - a rough idea of yearly spending.
4. The **Am I on track?** page is the summary. Every **?** button explains a term in plain words.
5. Turn on **two-step verification** under *Settings → Sign-in security* for extra protection.

How to read the main number: *92% chance of success* means that in 920 of 1,000 simulated futures the money lasted to the end of the plan. About 85% or more is generally considered comfortable. That is a rule of thumb, not a promise.

---

## Running it

### On a server, with Docker (recommended)

```bash
cp deploy/production.env.example deploy/production.env   # then fill in the passwords/keys it asks for
docker compose --env-file deploy/production.env up -d --build
```

Open `http://<server>:3000`. Put it behind HTTPS (for example Caddy or nginx) before using real data. Daily database backups are written to `./backups/`, and 14 days are kept. Restore steps are in `deploy/backup.sh`.

For a separate **staging** copy (its own database, its own port 3100):

```bash
cp deploy/staging.env.example deploy/staging.env
docker compose --env-file deploy/staging.env up -d --build
```

### For development

Requirements: Python 3.11+, Node 20+, PostgreSQL 16.

```bash
# database
createuser -P planner          # password: planner
createdb -O planner planner

# backend (http://localhost:8000, API docs at /api/docs)
cd backend
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload

# frontend (http://localhost:3000)
cd frontend
npm install
npm run dev
```

Tests:

```bash
cd backend && .venv/bin/pytest            # engine + API (SQLite)
TEST_DATABASE_URL=postgresql+psycopg://planner:planner@localhost:5432/planner_test .venv/bin/pytest tests/test_api.py
cd frontend && npx tsc --noEmit && npm run build
```

### Optional extras

- **AI assistant.** Out of the box a private built-in helper answers common questions and sends no data anywhere. To use a language model instead, set `AI_API_KEY`, `AI_MODEL` (any OpenRouter or OpenAI-compatible model) and `AI_DPA_CONFIRMED=true`. Each user must then also agree on the *Ask a question* page before any plan data is sent.
- **Account linking.** `AGGREGATION_PROVIDER=plaid` with Plaid credentials enables the provider interface. Manual entry and CSV import always work without it.

---

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): how the pieces fit together, the database, security and privacy.
- [docs/CALCULATIONS.md](docs/CALCULATIONS.md): every calculation, its sources, assumptions and known limitations.
- [docs/PROGRESS.md](docs/PROGRESS.md): what has been built, how it was tested, and open items.
