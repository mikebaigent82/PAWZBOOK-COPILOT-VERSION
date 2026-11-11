"""Tools the assistant may call.

The assistant never calculates. It can only ask the engine for results through
these functions and then explain them. It also cannot change anything: the one
"write" tool creates a *proposal* that the user must confirm in the app.

Tool results contain plan numbers only - no email addresses, account numbers or
institution names.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ..api.deps import Ctx
from ..engine.stress import CustomStress, list_historical, run_custom, run_historical
from ..models import AIProposal, Expense, Member
from ..services import runs
from ..services.glossary import GLOSSARY, lookup
from ..services.plan_builder import OneTimeExpense, ScenarioOverrides

ASSISTANT_MC_PATHS = 500
ASSISTANT_SEED = 20260101


class WhatIf(BaseModel):
    """A temporary change to try. Nothing is saved."""
    model_config = ConfigDict(extra="forbid")
    retire_years_later: int = Field(0, ge=-10, le=15, description="Everyone retires this many years later (negative = earlier).")
    retirement_age: int | None = Field(None, ge=40, le=85, description="Set the first person's retirement age.")
    spending_change_pct: float = Field(0, ge=-80, le=200, description="Change all regular spending by this percent, e.g. -10.")
    ss_claim_age: int | None = Field(None, ge=62, le=70, description="Everyone claims Social Security at this age.")
    return_change_pct: float = Field(0, ge=-10, le=10, description="Shift every expected return by this many percentage points.")
    one_time_expense_amount: float = Field(0, ge=0)
    one_time_expense_year: int | None = None

    def is_baseline(self) -> bool:
        return self == WhatIf()


def _members(ctx: Ctx) -> list[Member]:
    rows = list(ctx.db.scalars(select(Member).where(Member.household_id == ctx.hid)).unique())
    return sorted(rows, key=lambda m: (m.relationship_kind != "self", m.created_at))


def to_overrides(ctx: Ctx, w: WhatIf) -> ScenarioOverrides | None:
    if w.is_baseline():
        return None
    members = _members(ctx)
    ov = ScenarioOverrides(expense_scale=1 + w.spending_change_pct / 100, return_shift=w.return_change_pct / 100)
    for i, m in enumerate(members):
        age = m.retirement_age + w.retire_years_later
        if w.retirement_age is not None and i == 0:
            age = w.retirement_age
        if age != m.retirement_age:
            ov.retirement_age[m.id] = max(age, date.today().year - m.birth_year)
        if w.ss_claim_age is not None:
            ov.ss_claim_age[m.id] = w.ss_claim_age
    if w.one_time_expense_amount > 0:
        ov.one_time_expenses.append(OneTimeExpense(
            amount=w.one_time_expense_amount, year=w.one_time_expense_year or date.today().year + 1))
    return ov


def _brief(ctx: Ctx, ov: ScenarioOverrides | None) -> dict:
    proj = runs.projection(ctx, overrides=ov, store=ov is None)
    mc = runs.monte_carlo(ctx, n_paths=ASSISTANT_MC_PATHS, seed=ASSISTANT_SEED, overrides=ov, store=ov is None)
    s = proj["summary"]
    return {
        "chance_of_success": mc["success_probability"],
        "simulations": mc["n_paths"],
        "seed": ASSISTANT_SEED,
        "funded_in_average_return_projection": s["funded"],
        "first_shortfall_year": s["first_shortfall_year"],
        "plan_end_year": s["plan_end_year"],
        "ending_investments_todays_dollars": s["ending_portfolio_real"],
        "median_ending_investments_todays_dollars_simulated": mc["ending_portfolio_real"]["p50"],
        "lifetime_taxes_todays_dollars": s["lifetime_taxes_real"],
        "input_fingerprint": proj["meta"]["plan_hash"][:12],
    }


def get_plan_overview(ctx: Ctx) -> dict:
    plan, notes, _, _ = runs.resolve(ctx)
    year = plan.start_year
    by_type: dict[str, float] = {}
    for a in plan.accounts:
        by_type[a.tax_type] = by_type.get(a.tax_type, 0) + a.balance
    active_exp = [e for e in plan.expenses if (e.start_year or year) <= year <= (e.end_year or year)]
    return {
        "people": [{"name": m.name, "age": year - m.birth_year, "retirement_age": m.retirement_age,
                    "plan_to_age": m.life_expectancy, "social_security_claim_age": m.social_security.claim_age,
                    "social_security_monthly": m.social_security.monthly_benefit} for m in plan.members],
        "filing_status": plan.filing_status,
        "investments_by_account_type": {k: round(v, 2) for k, v in by_type.items()},
        "investments_total": round(sum(by_type.values()), 2),
        "property_and_business_value": round(sum(x.value for x in plan.assets), 2),
        "debts": round(sum(x.balance for x in plan.liabilities), 2),
        "annual_income_now": round(sum(i.amount for i in plan.incomes
                                       if (i.start_year or year) <= year <= (i.end_year or year)), 2),
        "annual_spending_now": {
            "essential": round(sum(e.amount for e in active_exp if e.category == "essential"), 2),
            "optional": round(sum(e.amount for e in active_exp if e.category == "discretionary"), 2),
        },
        "assumptions": {"inflation": plan.assumptions.inflation,
                        "withdrawal_order": plan.assumptions.withdrawal_strategy,
                        "roth_conversion": plan.assumptions.roth_conversion.mode,
                        "guardrails_on": plan.assumptions.guardrails.enabled},
        "results": _brief(ctx, None),
        "notes": notes,
    }


def run_what_if(ctx: Ctx, what_if: WhatIf) -> dict:
    ov = to_overrides(ctx, what_if)
    out = {"baseline": _brief(ctx, None)}
    if ov is not None:
        changed = _brief(ctx, ov)
        out["with_change"] = changed
        out["difference"] = {
            "chance_of_success": round(changed["chance_of_success"] - out["baseline"]["chance_of_success"], 4),
            "ending_investments_todays_dollars": round(
                changed["ending_investments_todays_dollars"] - out["baseline"]["ending_investments_todays_dollars"], 2),
            "lifetime_taxes_todays_dollars": round(
                changed["lifetime_taxes_todays_dollars"] - out["baseline"]["lifetime_taxes_todays_dollars"], 2),
        }
        out["change_tested"] = what_if.model_dump(exclude_defaults=True)
    return out


def yearly_details(ctx: Ctx, year: int) -> dict:
    proj = runs.projection(ctx)
    row = next((r for r in proj["rows"] if r["year"] == year), None)
    if row is None:
        return {"error": f"Year {year} is outside the plan ({proj['years'][0]}-{proj['years'][-1]})."}
    keep = ("year", "wages", "social_security", "other_income", "spending_total", "tax_total",
            "tax_federal_ordinary", "tax_federal_ltcg", "tax_state", "withdrawals_total", "rmd", "roth_conversion",
            "agi", "taxable_income", "marginal_rate", "portfolio", "net_worth", "shortfall", "price_index")
    return {"dollars": "future (nominal); divide by price_index for today's dollars",
            **{k: row[k] for k in keep}}


def roth_analysis(ctx: Ctx) -> dict:
    out = runs.roth(ctx)
    top = out["candidates"][:4]
    return {
        "recommended": out["recommended_key"],
        "conversion_window": out["window"],
        "options": [{"key": c["key"], "label": c["label"], "score": c["score"],
                     "lifetime_tax_and_medicare_change": c["vs_baseline"]["lifetime_cost"],
                     "after_tax_wealth_change": c["vs_baseline"]["after_tax_wealth"],
                     "heirs_value_change": c["vs_baseline"]["beneficiary_value"],
                     "total_converted": c["metrics"]["total_converted_nominal"]} for c in top],
        "method": out["method"],
        "limitations": out["limitations"],
    }


def stress_test(ctx: Ctx, scenario: str = "financial_crisis_2008", equity_drop_pct: float | None = None) -> dict:
    plan, _, _, _ = runs.resolve(ctx)
    if equity_drop_pct is not None:
        res = run_custom(plan, CustomStress(name=f"Stocks fall {equity_drop_pct:.0f}%",
                                            equity_return=-abs(equity_drop_pct) / 100))
    else:
        keys = [h["key"] for h in list_historical()]
        res = run_historical(plan, scenario if scenario in keys else "financial_crisis_2008")
    return {"name": res["name"], "label": res["label"], "starts_in": res["start_year"],
            "baseline": {k: res["baseline_summary"][k] for k in ("funded", "first_shortfall_year",
                                                                  "ending_portfolio_real")},
            "stressed": {k: res["stressed_summary"][k] for k in ("funded", "first_shortfall_year",
                                                                  "ending_portfolio_real")}}


def explain_term(ctx: Ctx, term: str) -> dict:
    found = lookup(term)
    return found or {"error": f"No glossary entry for '{term}'.", "available": sorted(GLOSSARY)}


CHANGE_KINDS = ("set_retirement_age", "set_ss_claim_age", "set_expense_amount", "set_guardrails",
                "set_withdrawal_strategy")


def propose_change(ctx: Ctx, conversation_id: str, kind: str, title: str, explanation: str = "",
                   person_name: str | None = None, value: float | str | bool | None = None,
                   expense_name: str | None = None) -> dict:
    if kind not in CHANGE_KINDS:
        return {"error": f"Unknown change '{kind}'. Allowed: {', '.join(CHANGE_KINDS)}"}
    change: dict = {"kind": kind, "value": value}
    if kind in ("set_retirement_age", "set_ss_claim_age"):
        members = _members(ctx)
        m = next((x for x in members if person_name and x.name.lower() == person_name.lower()), members[0])
        change.update(member_id=m.id, member_name=m.name)
    if kind == "set_expense_amount":
        e = next((x for x in ctx.db.scalars(select(Expense).where(Expense.household_id == ctx.hid))
                  if expense_name and x.name.lower() == expense_name.lower()), None)
        if e is None:
            return {"error": f"No expense named '{expense_name}'."}
        change.update(expense_id=e.id, expense_name=e.name)
    row = AIProposal(household_id=ctx.hid, conversation_id=conversation_id, title=title[:200],
                     explanation=explanation, change=change)
    ctx.db.add(row)
    ctx.db.flush()
    ctx.log("ai.proposal_created", "ai_proposal", row.id, {"kind": kind})
    return {"proposal_id": row.id, "status": "pending",
            "message": "The change has NOT been made. The user must press Confirm in the app."}


_WHAT_IF_SCHEMA = WhatIf.model_json_schema()
_WHAT_IF_SCHEMA.pop("title", None)

TOOL_SPECS = [
    {"name": "get_plan_overview",
     "description": "Summary of the household's plan and its current results (chance of success, projection).",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "run_what_if",
     "description": "Test a temporary change (retire later, spend less, different Social Security age, lower "
                    "returns, a one-time expense) and compare with the current plan. Saves nothing.",
     "parameters": _WHAT_IF_SCHEMA},
    {"name": "yearly_details",
     "description": "Income, spending, taxes and balances for one calendar year of the projection.",
     "parameters": {"type": "object", "properties": {"year": {"type": "integer"}}, "required": ["year"]}},
    {"name": "roth_analysis",
     "description": "Compare Roth conversion strategies on lifetime tax, after-tax wealth and value to heirs.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "stress_test",
     "description": "Replay a historical bad period (scenario key) or a custom stock-market drop.",
     "parameters": {"type": "object", "properties": {
         "scenario": {"type": "string", "enum": ["great_depression_1929", "stagflation_1973", "dotcom_2000",
                                                 "financial_crisis_2008", "inflation_shock_2022"]},
         "equity_drop_pct": {"type": "number"}}}},
    {"name": "explain_term",
     "description": "Plain-English explanation of a financial term used in the app.",
     "parameters": {"type": "object", "properties": {"term": {"type": "string"}}, "required": ["term"]}},
    {"name": "propose_change",
     "description": "Suggest a change to the saved plan. It is only applied if the user confirms it in the app.",
     "parameters": {"type": "object", "properties": {
         "kind": {"type": "string", "enum": list(CHANGE_KINDS)},
         "title": {"type": "string"}, "explanation": {"type": "string"},
         "person_name": {"type": "string"}, "expense_name": {"type": "string"},
         "value": {"description": "New age, amount, true/false, or strategy name."}},
         "required": ["kind", "title", "value"]}},
]


def execute(ctx: Ctx, conversation_id: str, name: str, args: dict) -> dict:
    """Run one tool call. Errors are returned as data so the assistant can explain them."""
    try:
        if name == "get_plan_overview":
            return get_plan_overview(ctx)
        if name == "run_what_if":
            return run_what_if(ctx, WhatIf.model_validate(args or {}))
        if name == "yearly_details":
            return yearly_details(ctx, int(args["year"]))
        if name == "roth_analysis":
            return roth_analysis(ctx)
        if name == "stress_test":
            return stress_test(ctx, **{k: v for k, v in (args or {}).items() if k in ("scenario", "equity_drop_pct")})
        if name == "explain_term":
            return explain_term(ctx, str(args.get("term", "")))
        if name == "propose_change":
            allowed = ("kind", "title", "explanation", "person_name", "value", "expense_name")
            return propose_change(ctx, conversation_id, **{k: v for k, v in (args or {}).items() if k in allowed})
        return {"error": f"Unknown tool '{name}'"}
    except Exception as exc:  # noqa: BLE001 - reported back to the assistant, never hidden
        detail = getattr(exc, "detail", None) or str(exc)
        return {"error": str(detail)}
