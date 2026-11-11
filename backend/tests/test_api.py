"""End-to-end API tests: sign-in, data isolation, calculations, reports, assistant, privacy.

Runs against SQLite by default; set TEST_DATABASE_URL to run against PostgreSQL.
"""
import os

import pyotp
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("ENVIRONMENT", "development")
os.environ["AI_API_KEY"] = ""

from app import db as dbmod  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import Base  # noqa: E402
from app.main import create_app  # noqa: E402
from app.security.core import rate_limiter  # noqa: E402

PASSWORD = "correct horse battery"


class Api:
    """Small wrapper that sends the CSRF header like the web app does."""

    def __init__(self, app):
        self.c = TestClient(app)

    def _headers(self):
        token = self.c.cookies.get("tg_csrf")
        return {"X-CSRF-Token": token} if token else {}

    def get(self, url, **kw):
        return self.c.get("/api" + url, **kw)

    def post(self, url, json=None, **kw):
        return self.c.post("/api" + url, json=json, headers=self._headers(), **kw)

    def put(self, url, json=None):
        return self.c.put("/api" + url, json=json, headers=self._headers())

    def patch(self, url, json=None):
        return self.c.patch("/api" + url, json=json, headers=self._headers())

    def delete(self, url):
        return self.c.delete("/api" + url, headers=self._headers())

    def register(self, email="dad@example.com", name="Dad"):
        r = self.post("/auth/register", {"email": email, "password": PASSWORD, "display_name": name})
        assert r.status_code == 200, r.text
        return r.json()


@pytest.fixture
def app():
    url = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")
    engine = dbmod.configure(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    rate_limiter.reset()
    yield create_app()
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def api(app):
    a = Api(app)
    a.register()
    return a


@pytest.fixture
def sample(api):
    assert api.post("/sample-data").status_code == 200
    return api


class TestAuth:
    def test_register_login_logout(self, app):
        a = Api(app)
        me = a.register()
        assert me["email"] == "dad@example.com" and me["simple_mode"] is True
        assert a.get("/auth/me").status_code == 200
        assert a.post("/auth/logout").status_code == 200
        assert a.get("/auth/me").status_code == 401
        r = a.post("/auth/login", {"email": "dad@example.com", "password": "wrong password"})
        assert r.status_code == 401
        r = a.post("/auth/login", {"email": "DAD@example.com", "password": PASSWORD})
        assert r.status_code == 200 and r.json()["mfa_required"] is False
        assert a.get("/household").status_code == 200

    def test_weak_password_and_duplicate_email(self, app):
        a = Api(app)
        r = a.post("/auth/register", {"email": "x@example.com", "password": "short", "display_name": "X"})
        assert r.status_code == 422 and "10 characters" in r.json()["detail"]
        a.register()
        r = Api(app).post("/auth/register", {"email": "dad@example.com", "password": PASSWORD, "display_name": "Y"})
        assert r.status_code == 409

    def test_session_cookie_flags_and_csrf(self, api):
        cookie = next(c for c in api.c.cookies.jar if c.name == "tg_session")
        assert cookie.has_nonstandard_attr("HttpOnly")
        r = api.c.post("/api/members", json={"name": "A", "birth_year": 1960})  # no CSRF header
        assert r.status_code == 403
        r = api.c.post("/api/members", json={"name": "A", "birth_year": 1960}, headers={"X-CSRF-Token": "forged"})
        assert r.status_code == 403

    def test_mfa_flow(self, api):
        setup = api.post("/auth/mfa/setup").json()
        assert setup["otpauth_uri"].startswith("otpauth://totp/")
        assert api.post("/auth/mfa/enable", {"code": "000000"}).status_code == 401
        codes = api.post("/auth/mfa/enable", {"code": pyotp.TOTP(setup["secret"]).now()}).json()["recovery_codes"]
        assert len(codes) == 8
        api.post("/auth/logout")
        r = api.post("/auth/login", {"email": "dad@example.com", "password": PASSWORD})
        assert r.json() == {"mfa_required": True, "user": None}
        blocked = api.get("/household")
        assert blocked.status_code == 401 and blocked.headers["x-mfa-required"] == "1"
        assert api.post("/auth/mfa/verify", {"code": "123456"}).status_code == 401
        assert api.post("/auth/mfa/verify", {"code": pyotp.TOTP(setup["secret"]).now()}).status_code == 200
        assert api.get("/household").status_code == 200
        # recovery code works once
        api.post("/auth/logout")
        api.post("/auth/login", {"email": "dad@example.com", "password": PASSWORD})
        assert api.post("/auth/mfa/verify", {"code": codes[0]}).status_code == 200
        api.post("/auth/logout")
        api.post("/auth/login", {"email": "dad@example.com", "password": PASSWORD})
        assert api.post("/auth/mfa/verify", {"code": codes[0]}).status_code == 401

    def test_lockout_after_repeated_failures(self, app):
        a = Api(app)
        a.register()
        a.post("/auth/logout")
        for _ in range(get_settings().max_failed_logins):
            assert a.post("/auth/login", {"email": "dad@example.com", "password": "nope nope nope"}).status_code == 401
        assert a.post("/auth/login", {"email": "dad@example.com", "password": PASSWORD}).status_code == 423

    def test_rate_limit(self, app):
        a = Api(app)
        codes = [a.post("/auth/login", {"email": "nobody@example.com", "password": "x" * 12}).status_code
                 for _ in range(get_settings().rate_limit_auth_per_minute + 2)]
        assert codes[-1] == 429

    def test_password_change_signs_out_other_sessions(self, app):
        a, b = Api(app), Api(app)
        a.register()
        assert b.post("/auth/login", {"email": "dad@example.com", "password": PASSWORD}).status_code == 200
        r = a.post("/auth/password", {"current_password": PASSWORD, "new_password": "a brand new passphrase"})
        assert r.status_code == 200
        assert a.get("/auth/me").status_code == 200
        assert b.get("/auth/me").status_code == 401


class TestDataEntry:
    def test_manual_entry_to_projection(self, api):
        """The whole plan can be built by hand, without any account connection."""
        r = api.post("/projection")
        assert r.status_code == 422 and "person" in r.json()["detail"]
        m = api.post("/members", {"name": "Dad", "birth_year": 1958, "retirement_age": 67, "life_expectancy": 93,
                                  "ss_monthly_benefit": 2600, "ss_claim_age": 67}).json()
        assert m["age"] >= 67 and m["ss_monthly_benefit"] == 2600
        acct = api.post("/accounts", {"name": "IRA", "tax_type": "traditional", "member_id": m["id"],
                                      "balance": 600000, "allocation_preset": "balanced"})
        assert acct.status_code == 201 and acct.json()["allocation_preset"] == "balanced"
        assert api.post("/accounts", {"name": "Bank", "tax_type": "cash", "balance": 40000}).status_code == 201
        assert api.post("/expenses", {"name": "Living", "amount": 55000}).status_code == 201
        assert api.post("/pensions", {"name": "Pension", "member_id": m["id"], "annual_amount": 12000,
                                      "start_age": 65}).status_code == 201
        proj = api.post("/projection").json()
        assert proj["summary"]["plan_end_age_oldest"] == 93
        assert proj["rows"][0]["other_income"] == 12000
        assert proj["meta"]["tax_rule_versions"]
        assert api.post("/projection").json()["cached"] is True
        nw = api.get("/networth").json()
        assert nw["investments"] == 640000 and nw["net_worth"] == 640000

    def test_validation_messages_are_readable(self, api):
        r = api.post("/accounts", {"name": "IRA", "tax_type": "roth", "balance": 10})
        assert r.status_code == 422 and "choose the owner" in r.json()["detail"]
        r = api.post("/liabilities", {"name": "Loan", "balance": 100000, "interest_rate": 0.12, "monthly_payment": 500})
        assert r.status_code == 422 and "never be paid off" in r.json()["detail"]
        r = api.post("/expenses", {"name": "Roof", "amount": 100, "kind": "one_time"})
        assert r.status_code == 422 and "year" in r.json()["detail"]
        r = api.post("/accounts", {"name": "X", "tax_type": "cash", "balance": -5})
        assert r.status_code == 422
        r = api.patch("/household", {"filing_status": "mfj"})
        assert r.status_code == 422 and "spouse" in r.json()["detail"]

    def test_crud_update_delete(self, api):
        e = api.post("/expenses", {"name": "Travel", "amount": 5000, "category": "discretionary"}).json()
        u = api.put(f"/expenses/{e['id']}", {"name": "Travel", "amount": 7000, "category": "discretionary"})
        assert u.json()["amount"] == 7000
        assert api.delete(f"/expenses/{e['id']}").status_code == 204
        assert api.get("/expenses").json() == []
        assert api.put(f"/expenses/{e['id']}", {"name": "T", "amount": 1}).status_code == 404

    def test_csv_import(self, api):
        csv_text = ("account,tax_type,symbol,name,value,cost_basis,asset_class\n"
                    "Brokerage,taxable,VTI,,\"$100,000\",60000,\n"
                    "Brokerage,taxable,ACME,Acme Corp,50000,10000,us_stocks\n"
                    "Brokerage,taxable,BAD,Broken,,,\n"
                    "Old 401k,401k,BND,,80000,,\n")
        r = api.post("/import/csv", {"kind": "holdings", "content": csv_text}).json()
        assert r["imported"] == 3 and r["errors"] == [{"row": 4, "message": "missing or negative value"}]
        accounts = {a["name"]: a for a in api.get("/accounts").json()}
        assert accounts["Brokerage"]["value"] == 150000 and accounts["Old 401k"]["tax_type"] == "traditional"
        an = api.get("/analytics/portfolio").json()
        assert an["total_value"] == 230000
        assert {c["key"]: c["value"] for c in an["by_asset_class"]} == {"us_stocks": 150000, "bonds": 80000}
        assert any(f["code"] == "single_position" for f in an["concentration"]["flags"])
        r = api.post("/import/csv", {"kind": "expenses", "content": "name,amount,category\nFood,9000,essential\n"})
        assert r.json()["imported"] == 1
        assert set(api.get("/import/templates").json()) == {"accounts", "holdings", "transactions", "expenses"}

    def test_holdings_and_look_through(self, api):
        a = api.post("/accounts", {"name": "Brokerage", "tax_type": "taxable", "balance": 0}).json()
        r = api.post(f"/accounts/{a['id']}/holdings", {
            "symbol": "BAL", "name": "Balanced fund", "value": 100000, "composition": [
                {"kind": "asset_class", "key": "us_stocks", "weight": 0.6},
                {"kind": "asset_class", "key": "bonds", "weight": 0.4},
                {"kind": "security", "key": "ACME", "name": "Acme", "weight": 0.2}]})
        assert r.status_code == 201 and r.json()["value"] == 100000
        an = api.get("/analytics/portfolio").json()
        assert {c["key"]: c["share"] for c in an["by_asset_class"]} == {"us_stocks": 0.6, "bonds": 0.4}
        assert an["look_through"]["covered_share"] == 1.0
        assert next(p for p in an["positions"] if p["key"] == "ACME")["through_funds"] == 20000
        bad = api.post(f"/accounts/{a['id']}/holdings", {"symbol": "X", "value": 1, "composition": [
            {"kind": "asset_class", "key": "bonds", "weight": 0.8}, {"kind": "asset_class", "key": "cash", "weight": 0.8}]})
        assert bad.status_code == 422


class TestIsolation:
    def test_users_cannot_see_or_touch_each_others_data(self, app):
        dad, other = Api(app), Api(app)
        dad.register()
        other.register("someone@example.com", "Someone")
        dad.post("/sample-data")
        acct = dad.get("/accounts").json()[0]
        member = dad.get("/members").json()[0]
        assert other.get("/accounts").json() == []
        assert other.get("/members").json() == []
        payload = {"name": "Hacked", "tax_type": "cash", "balance": 1}
        assert other.put(f"/accounts/{acct['id']}", payload).status_code == 404
        assert other.delete(f"/accounts/{acct['id']}").status_code == 404
        assert other.post(f"/accounts/{acct['id']}/holdings", {"symbol": "X", "value": 1}).status_code == 404
        # cannot attach own rows to someone else's member
        r = other.post("/accounts", {"name": "Mine", "tax_type": "roth", "member_id": member["id"], "balance": 1})
        assert r.status_code == 404
        # cannot switch into another household through the header
        r = other.c.get("/api/accounts", headers={"X-Household-Id": dad.get("/household").json()["id"]})
        assert r.status_code == 404
        assert dad.get("/accounts").json()[0]["name"] == acct["name"]
        assert other.get("/audit").json() != dad.get("/audit").json()


class TestCalculations:
    def test_sample_data_full_flow(self, sample):
        hh = sample.get("/household").json()
        assert hh["is_demo"] is True and "fictional" in hh["name"].lower()
        proj = sample.post("/projection").json()
        assert len(proj["rows"]) == len(proj["years"]) and proj["notes"] == []
        mc1 = sample.post("/monte-carlo", {"n_paths": 400, "seed": 7}).json()
        mc2 = sample.post("/monte-carlo", {"n_paths": 400, "seed": 7}).json()
        assert mc2["cached"] is True and mc1["portfolio_real"] == mc2["portfolio_real"]
        assert mc1["meta"]["seed"] == 7 and mc1["meta"]["plan_hash"] == proj["meta"]["plan_hash"]
        other_seed = sample.post("/monte-carlo", {"n_paths": 400, "seed": 8}).json()
        assert other_seed["portfolio_real"] != mc1["portfolio_real"]
        runs = sample.get("/monte-carlo/runs").json()
        assert len(runs) == 2
        stored = sample.get(f"/monte-carlo/runs/{runs[0]['id']}").json()
        assert stored["input_snapshot"]["members"][0]["name"] == "Pat"
        assert sample.post("/monte-carlo", {"n_paths": 50}).status_code == 422
        assert sample.post("/monte-carlo", {"n_paths": 400, "distribution": "student_t",
                                            "degrees_of_freedom": 4}).status_code == 200

    def test_changing_data_changes_fingerprint_and_result(self, sample):
        before = sample.post("/projection").json()
        e = next(x for x in sample.get("/expenses").json() if x["category"] == "discretionary")
        sample.put(f"/expenses/{e['id']}", {"name": e["name"], "amount": e["amount"] * 2, "category": "discretionary"})
        after = sample.post("/projection").json()
        assert after["cached"] is False
        assert after["meta"]["plan_hash"] != before["meta"]["plan_hash"]
        assert after["summary"]["ending_portfolio_real"] < before["summary"]["ending_portfolio_real"]

    def test_insights_and_levers(self, sample):
        ins = sample.get("/insights").json()
        assert ins["status"] in ("on_track", "watch", "at_risk")
        assert "possible futures" in ins["points"][0]["text"]
        assert len(ins["chart"]["p50_real"]) == len(ins["chart"]["years"])
        assert "not guarantees" in ins["disclaimer"]
        lev = sample.get("/insights/levers").json()
        by_key = {x["key"]: x for x in lev["levers"]}
        assert by_key["spend_less"]["change"] >= 0 >= by_key["spend_more"]["change"]
        assert by_key["retire_later"]["change"] >= 0

    def test_assumptions_are_versioned_and_overridable(self, sample):
        plan = sample.get("/plan").json()
        assert plan["assumption_version"] == 1 and plan["assumptions"]["inflation"] == 0.025
        base = sample.post("/projection").json()
        r = sample.patch("/plan/assumptions", {"changes": {"inflation": 0.04, "guardrails": {"enabled": True}},
                                                "note": "Higher inflation"})
        assert r.json()["assumption_version"] == 2
        assert r.json()["assumptions"]["guardrails"]["cut_pct"] == 0.1  # untouched nested values are kept
        hist = sample.get("/plan/assumptions/history").json()
        assert [h["version"] for h in hist] == [2, 1] and hist[1]["payload"]["inflation"] == 0.025
        assert sample.post("/projection").json()["summary"] != base["summary"]
        bad = sample.patch("/plan/assumptions", {"changes": {"inflation": "lots"}})
        assert bad.status_code == 422
        assert sample.patch("/plan/assumptions", {"changes": {"made_up": 1}}).status_code == 422
        ac = sample.put("/plan/asset-classes/us_stocks", {"name": "US stocks", "expected_return": 0.05,
                                                          "volatility": 0.16})
        assert ac.status_code == 200
        assert sample.get("/plan/input").json()["input"]["asset_classes"][0]["expected_return"] == 0.05
        assert sample.patch("/household", {"state": "CA"}).status_code == 200
        assert sample.get("/plan").json()["assumptions"]["state_tax"] == {
            "state": "CA", "rate": 0.04, "taxes_social_security": False, "exempts_retirement_income": False}

    def test_roth_optimizer_and_apply(self, sample):
        out = sample.post("/roth/optimize").json()
        assert len(out["candidates"]) > 5 and out["current_conversion"]["mode"] == "none"
        pick = next(c for c in out["candidates"] if c["key"] != "none")
        r = sample.post("/roth/apply", {"strategy_id": out["id"], "key": pick["key"]})
        assert r.status_code == 200 and r.json()["roth_conversion"]["mode"] == pick["conversion"]["mode"]
        proj = sample.post("/projection").json()
        assert proj["summary"]["total_roth_conversions_nominal"] == pytest.approx(
            pick["metrics"]["total_converted_nominal"], abs=1)
        assert sample.post("/roth/apply", {"strategy_id": out["id"], "key": "nope"}).status_code == 404
        strat = sample.post("/withdrawal-strategies/compare").json()
        assert len(strat["candidates"]) == 4

    def test_stress_tests(self, sample):
        hist = sample.get("/stress/historical").json()
        assert len(hist) == 5
        r = sample.post("/stress/run", {"kind": "historical", "key": "financial_crisis_2008"}).json()
        assert r["stressed_summary"]["ending_portfolio_real"] < r["baseline_summary"]["ending_portfolio_real"]
        assert "HISTORICAL" in r["label"]
        r = sample.post("/stress/run", {"kind": "custom", "custom": {"equity_return": -0.5, "inflation": 0.09,
                                                                     "inflation_years": 3}}).json()
        assert "HYPOTHETICAL" in r["label"] and len(r["applied"]) == 3
        r = sample.post("/stress/run", {"kind": "sequence", "years": 4}).json()
        assert len(r["applied"]) == 8
        assert sample.post("/stress/run", {"kind": "historical", "key": "unknown"}).status_code == 422

    def test_scenarios_never_change_the_baseline(self, sample):
        base = sample.post("/projection").json()
        members = sample.get("/members").json()
        ov = {"retirement_age": {members[0]["id"]: members[0]["retirement_age"] + 3}, "expense_scale": 0.9,
              "one_time_expenses": [{"name": "Boat", "amount": 40000, "year": base["years"][5]}]}
        s = sample.post("/scenarios", {"name": "Work longer, spend less", "overrides": ov})
        assert s.status_code == 201
        sid = s.json()["id"]
        cmp_ = sample.post("/scenarios/compare", {"scenario_ids": [sid], "n_paths": 300}).json()
        cur, alt = cmp_["columns"]
        assert cur["is_baseline"] and cur["input_hash"] == base["meta"]["plan_hash"]
        assert alt["input_hash"] != cur["input_hash"]
        assert alt["success_probability"] >= cur["success_probability"]
        assert sample.post("/projection").json()["meta"]["plan_hash"] == base["meta"]["plan_hash"]
        assert sample.get("/members").json()[0]["retirement_age"] == members[0]["retirement_age"]
        listing = sample.get("/scenarios").json()
        assert listing["baseline"]["protected"] is True and len(listing["scenarios"]) == 1
        bad = sample.post("/scenarios", {"name": "Bad", "overrides": {"surprise": 1}})
        assert bad.status_code == 422
        assert sample.delete(f"/scenarios/{sid}").status_code == 204


class TestReportsAssistantPrivacy:
    def test_reports_in_three_formats(self, sample):
        pdf = sample.post("/reports", {"file_format": "pdf"}).json()
        xlsx = sample.post("/reports", {"file_format": "xlsx"}).json()
        csv_ = sample.post("/reports", {"file_format": "csv"}).json()
        d = sample.get(f"/reports/{pdf['id']}/download")
        assert d.content[:5] == b"%PDF-" and d.headers["content-type"] == "application/pdf"
        assert sample.get(f"/reports/{xlsx['id']}/download").content[:2] == b"PK"
        text = sample.get(f"/reports/{csv_['id']}/download").text
        assert "not a guarantee" in text and "portfolio" in text
        assert len(sample.get("/reports").json()) == 3

    def test_assistant_demo_mode(self, sample):
        st = sample.get("/assistant/status").json()
        assert st["mode"] == "demo" and st["provider_configured"] is False
        r = sample.post("/assistant/chat", {"message": "Am I on track?"}).json()
        assert r["mode"] == "demo" and "possible futures" in r["reply"]
        assert r["tools_used"][0]["name"] == "get_plan_overview"
        cid = r["conversation_id"]
        r = sample.post("/assistant/chat", {"message": "What if I retire 2 years later?", "conversation_id": cid}).json()
        assert r["tools_used"] == [{"name": "run_what_if", "arguments": {"retire_years_later": 2}}]
        assert "has not changed" in r["reply"]
        r = sample.post("/assistant/chat", {"message": "what is a roth conversion?", "conversation_id": cid}).json()
        assert "Roth conversion" in r["reply"] and r["tools_used"][0]["name"] == "explain_term"
        r = sample.post("/assistant/chat", {"message": "What happens in a crash like 2008?"}).json()
        assert "not a prediction" in r["reply"]
        conv = sample.get(f"/assistant/conversations/{cid}").json()
        assert [m["role"] for m in conv["messages"]] == ["user", "assistant"] * 3

    def test_assistant_proposals_need_confirmation(self, sample):
        from app.ai import tools
        from app.api.deps import Ctx
        from app.models import AIConversation, Household, HouseholdAccess, User
        cid = sample.post("/assistant/chat", {"message": "hello"}).json()["conversation_id"]
        db = next(dbmod.get_db())
        user = db.query(User).one()
        hh = db.get(Household, db.query(HouseholdAccess).one().household_id)
        ctx = Ctx(db=db, request=None, user=user, household=hh, role="owner")
        out = tools.execute(ctx, cid, "propose_change", {"kind": "set_retirement_age", "title": "Retire at 68",
                                                         "person_name": "Pat", "value": 68})
        db.commit()
        assert out["status"] == "pending" and db.get(AIConversation, cid) is not None
        assert sample.get("/members").json()[0]["retirement_age"] == 66       # nothing changed yet
        r = sample.post(f"/assistant/proposals/{out['proposal_id']}", {"decision": "apply"})
        assert r.json()["status"] == "applied"
        assert sample.get("/members").json()[0]["retirement_age"] == 68
        assert sample.post(f"/assistant/proposals/{out['proposal_id']}", {"decision": "apply"}).status_code == 409
        assert tools.execute(ctx, cid, "propose_change", {"kind": "delete_everything", "title": "x", "value": 1})["error"]
        assert "error" in tools.execute(ctx, cid, "no_such_tool", {})
        db.close()

    def test_consent_is_recorded_and_revocable(self, sample):
        st = sample.post("/assistant/consent", {"consent": True}).json()
        assert st["consent_given"] is True and st["mode"] == "demo"  # no provider configured -> still local
        assert sample.post("/assistant/consent", {"consent": False}).json()["consent_given"] is False
        actions = [a["action"] for a in sample.get("/audit").json()]
        assert "ai.consent_given" in actions and "ai.consent_withdrawn" in actions

    def test_export_and_delete_account(self, sample):
        sample.post("/projection")
        export = sample.get("/privacy/export").json()
        assert export["user"]["email"] == "dad@example.com"
        assert len(export["members"]) == 2 and export["accounts"] and export["projection_results"]
        assert "password_hash" not in str(export) and "totp" not in str(export)
        assert sample.post("/privacy/delete-account", {"password": "wrong", "confirm": "DELETE"}).status_code == 401
        assert sample.post("/privacy/delete-account", {"password": PASSWORD, "confirm": "DELETE"}).status_code == 200
        assert sample.get("/auth/me").status_code == 401
        assert sample.post("/auth/login", {"email": "dad@example.com", "password": PASSWORD}).status_code == 401
        from app import models as M
        db = next(dbmod.get_db())
        for model in (M.User, M.Household, M.Member, M.Account, M.Holding, M.ProjectionResult, M.UserSession):
            assert db.query(model).count() == 0, model.__tablename__
        db.close()

    def test_audit_trail_and_misc(self, sample):
        actions = [a["action"] for a in sample.get("/audit").json()]
        assert "sample_data.load" in actions and "auth.register" in actions
        assert len(sample.get("/glossary").json()) > 20
        link = sample.get("/linking/status").json()
        assert link["available"] is False and "never" in link["credentials_note"]
        assert sample.post("/linking/token").status_code == 503
        assert sample.c.get("/api/health").json()["status"] == "ok"
        assert sample.c.get("/api/about").json()["ai_mode"] == "demo"
        r = sample.c.get("/api/health")
        assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"


class TestLiveAssistant:
    """The live path with a scripted model: it may only act through tools, and
    nothing is sent anywhere unless a provider is configured AND the user consented."""

    @pytest.fixture
    def live(self, sample, monkeypatch):
        s = get_settings()
        monkeypatch.setattr(s, "ai_api_key", "test-key")
        monkeypatch.setattr(s, "ai_model", "test/model")
        monkeypatch.setattr(s, "ai_dpa_confirmed", True)
        return sample

    def test_no_external_call_without_consent(self, live, monkeypatch):
        from app.providers import llm

        def boom(self, messages, tools):
            raise AssertionError("the external AI service must not be called without consent")
        monkeypatch.setattr(llm.ChatProvider, "complete", boom)
        st = live.get("/assistant/status").json()
        assert st["mode"] == "demo" and st["consent_required_for_live"] is True
        assert live.post("/assistant/chat", {"message": "Am I on track?"}).json()["mode"] == "demo"

    def test_tool_calling_loop(self, live, monkeypatch):
        from app.providers import llm
        seen = []

        def scripted(self, messages, tools):
            seen.append(messages)
            assert messages[0]["role"] == "system" and "Never do arithmetic" in messages[0]["content"]
            assert {t["name"] for t in tools} >= {"run_what_if", "propose_change", "get_plan_overview"}
            if len(seen) == 1:
                return {"content": "", "tool_calls": [{"id": "c1", "name": "run_what_if",
                                                       "arguments": {"spending_change_pct": -10}}]}
            tool_msg = messages[-1]
            assert tool_msg["role"] == "tool" and "chance_of_success" in tool_msg["content"]
            return {"content": "Spending 10% less raises your chance of success.", "tool_calls": []}
        monkeypatch.setattr(llm.ChatProvider, "complete", scripted)
        assert live.post("/assistant/consent", {"consent": True}).json()["mode"] == "live"
        r = live.post("/assistant/chat", {"message": "What if I spend less?"}).json()
        assert r["mode"] == "live" and r["reply"].startswith("Spending 10% less")
        assert r["tools_used"] == [{"name": "run_what_if", "arguments": {"spending_change_pct": -10}}]
        sent = str(seen)
        assert "dad@example.com" not in sent and "Example Brokerage" not in sent  # data minimisation
        conv = live.get(f"/assistant/conversations/{r['conversation_id']}").json()
        assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]

    def test_falls_back_to_helper_when_service_is_down(self, live, monkeypatch):
        from app.providers import llm

        def down(self, messages, tools):
            raise llm.LLMError("The AI service could not be reached (ConnectError).")
        monkeypatch.setattr(llm.ChatProvider, "complete", down)
        live.post("/assistant/consent", {"consent": True})
        r = live.post("/assistant/chat", {"message": "Am I on track?"}).json()
        assert r["mode"] == "demo" and "built-in helper answered" in r["notice"]


def test_scenario_preview_saves_nothing(sample):
    members = sample.get("/members").json()
    before = sample.get("/scenarios").json()["scenarios"]
    r = sample.post("/scenarios/preview", {"overrides": {"expense_scale": 0.8,
                                                         "ss_claim_age": {members[0]["id"]: 70}}, "n_paths": 300})
    assert r.status_code == 200, r.text
    cur, alt = r.json()["columns"]
    assert cur["is_baseline"] and not alt["is_baseline"]
    assert alt["success_probability"] >= cur["success_probability"]
    assert sample.get("/scenarios").json()["scenarios"] == before
