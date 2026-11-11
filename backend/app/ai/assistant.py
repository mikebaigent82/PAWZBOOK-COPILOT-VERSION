"""The plan assistant.

Two modes:
* live - a language model (via an OpenAI/OpenRouter-compatible API) that may
  only call the tools in ``tools.py``. Used only when the operator configured a
  provider and confirmed a data-processing agreement, AND the user consented.
* demo - a built-in helper with fixed rules. It recognises common questions,
  calls the same tools and fills the answers into templates. No data leaves the
  server. It is always labelled as the built-in helper.

In both modes every number comes from the calculation engine.
"""
from __future__ import annotations

import json
import re

from sqlalchemy import select

from ..api.deps import Ctx
from ..config import get_settings
from ..models import AIConversation, AIMessage, AIProposal
from ..providers.llm import ChatProvider, LLMError
from ..services.glossary import GLOSSARY
from . import tools

CONSENT_VERSION = "2026-11"
MAX_TOOL_ROUNDS = 6
MAX_HISTORY = 30

CONSENT_TEXT = (
    "To answer your questions, the assistant sends your question and summary numbers from your plan (ages, "
    "balances by account type, income, spending, results) to an external AI service. It does not send your "
    "email address, account numbers or the names of your banks. You can withdraw this permission at any time "
    "in Settings; the built-in helper keeps working without it."
)

SYSTEM_PROMPT = """You are the plan assistant inside a retirement-planning app. The person you are helping
may have no financial background, so use plain, friendly language, short sentences and everyday words.
Explain any financial term the first time you use it.

Strict rules:
1. Never do arithmetic or estimate numbers yourself. Every number you state must come from a tool result
   in this conversation. If you need a number, call a tool.
2. Say whether amounts are in today's dollars (inflation-adjusted) or future dollars.
3. You cannot change the plan. To suggest a change, call propose_change and tell the person it will only
   happen if they press Confirm.
4. Results are estimates based on assumptions, not guarantees. You do not give financial, tax or legal
   advice; describe what the numbers show and what options exist.
5. Historical stress tests replay the past. Never present them as predictions.
6. If a tool returns an error, say so plainly. Never invent data."""

SUGGESTIONS = [
    "Am I on track?",
    "What if I retire 2 years later?",
    "What if I spend 10% less?",
    "What if we claim Social Security at 70?",
    "Would a Roth conversion help?",
    "What happens in a crash like 2008?",
    "What is a Roth conversion?",
]


def status(ctx: Ctx) -> dict:
    s = get_settings()
    consent = ctx.user.ai_consent_at is not None
    configured = s.ai_live
    return {
        "mode": "live" if configured and consent else "demo",
        "provider_configured": configured,
        "consent_given": consent,
        "consent_required_for_live": configured and not consent,
        "consent_text": CONSENT_TEXT,
        "model": s.ai_model if configured else None,
        "suggestions": SUGGESTIONS,
        "demo_note": "You are using the built-in helper. It understands common questions and answers with "
                     "numbers from your plan. Nothing is sent outside this app.",
    }


# ----------------------------------------------------------------------------- demo helper


def _money(x: float) -> str:
    return f"${x:,.0f}"


def _pct(x: float) -> str:
    return f"{x:.0%}"


def _verdict(p: float) -> str:
    if p >= 0.85:
        return "That is generally considered a comfortable level."
    if p >= 0.70:
        return "That is fairly good, but there is some room to make the plan sturdier."
    return "That is lower than most people are comfortable with, so it is worth looking at changes."


def _baseline_text(b: dict) -> str:
    text = (f"I tested your plan in {b['simulations']:,} possible futures. Your money lasted in "
            f"**{_pct(b['chance_of_success'])}** of them. {_verdict(b['chance_of_success'])}\n\n")
    if b["funded_in_average_return_projection"]:
        text += (f"If investments simply earn their average return every year, your savings last through "
                 f"{b['plan_end_year']} with about {_money(b['ending_investments_todays_dollars'])} left "
                 f"(in today's dollars).")
    else:
        text += (f"If investments simply earn their average return every year, your savings would run short "
                 f"in {b['first_shortfall_year']}.")
    return text


def _what_if_text(label: str, res: dict) -> str:
    if "with_change" not in res:
        return _baseline_text(res["baseline"])
    b, c, d = res["baseline"], res["with_change"], res["difference"]
    direction = "up" if d["chance_of_success"] > 0.0005 else "down" if d["chance_of_success"] < -0.0005 else "unchanged"
    text = (f"**{label}**\n\n"
            f"- Chance your money lasts: {_pct(b['chance_of_success'])} now, **{_pct(c['chance_of_success'])}** "
            f"with this change ({direction}).\n"
            f"- Money left at the end (average-return projection, today's dollars): "
            f"{_money(b['ending_investments_todays_dollars'])} now, {_money(c['ending_investments_todays_dollars'])} "
            f"with this change.\n"
            f"- Lifetime taxes (today's dollars): {_money(b['lifetime_taxes_todays_dollars'])} now, "
            f"{_money(c['lifetime_taxes_todays_dollars'])} with this change.\n\n"
            f"This was only a test. Your saved plan has not changed.")
    return text


def _demo(ctx: Ctx, conversation_id: str, message: str) -> tuple[str, list[dict]]:
    """Rule-based helper. Returns (reply, tool trace)."""
    text = message.lower().strip()
    trace: list[dict] = []

    def call(name: str, **args) -> dict:
        result = tools.execute(ctx, conversation_id, name, args)
        trace.append({"name": name, "arguments": args, "result": result})
        return result

    def fail(result: dict) -> str | None:
        if "error" in result:
            return f"I could not work that out yet: {result['error']}"
        return None

    # explain a term
    m = re.search(r"(?:what is|what's|what are|what does|explain|meaning of|define)\s+(?:an?\s+|the\s+)?(.+?)(?:\s+mean)?\??$", text)
    if m:
        term = m.group(1).strip(" ?.")
        aliases = {"rmd": "rmd", "required minimum": "rmd", "monte carlo": "monte_carlo", "chance of success": "monte_carlo",
                   "roth conversion": "roth_conversion", "roth": "roth", "guardrail": "guardrails", "irmaa": "irmaa",
                   "inflation": "inflation", "today's dollars": "todays_dollars", "todays dollars": "todays_dollars",
                   "net worth": "net_worth", "stress test": "stress_test", "sequence": "sequence_risk",
                   "look-through": "look_through", "look through": "look_through", "tax bracket": "marginal_rate",
                   "social security": "social_security", "401": "traditional", "ira": "traditional",
                   "cost basis": "cost_basis", "volatility": "volatility", "seed": "seed"}
        key = next((v for k, v in aliases.items() if k in term), None)
        found = call("explain_term", term=key or term)
        if "error" not in found:
            return f"**{found['term']}**\n\n{found['plain']}", trace
        trace.clear()

    if "roth" in text:
        r = call("roth_analysis")
        if (err := fail(r)):
            return err, trace
        best = next(o for o in r["options"] if o["key"] == r["recommended"])
        if r["recommended"] == "none" or len(r["options"]) == 1:
            return ("A Roth conversion means moving money from a pre-tax account to a Roth account and paying "
                    "the tax now. I compared several ways of doing this for your plan, and none of them came "
                    "out ahead of leaving things as they are."), trace
        lines = "\n".join(
            f"- {o['label']}: lifetime tax and Medicare cost {'down' if o['lifetime_tax_and_medicare_change'] < 0 else 'up'} "
            f"{_money(abs(o['lifetime_tax_and_medicare_change']))}, value to heirs "
            f"{'up' if o['heirs_value_change'] >= 0 else 'down'} {_money(abs(o['heirs_value_change']))}"
            for o in r["options"][:3])
        return ("A Roth conversion means moving money from a pre-tax account to a Roth account. You pay tax on "
                "it now so it can grow tax-free later.\n\n"
                f"I compared several strategies. The best-scoring one is: **{best['label']}**.\n\n"
                f"Top options compared with doing nothing (today's dollars):\n{lines}\n\n"
                "This comparison uses average returns and today's tax rules. It is an estimate, not tax advice. "
                "You can see every option on the Taxes page."), trace

    if re.search(r"crash|2008|recession|stress|market (drop|fall)|downturn|depression|bear", text):
        scenario = "financial_crisis_2008"
        if "depression" in text or "1929" in text:
            scenario = "great_depression_1929"
        elif "dot" in text or "2000" in text:
            scenario = "dotcom_2000"
        elif "197" in text or "stagflation" in text:
            scenario = "stagflation_1973"
        elif "2022" in text:
            scenario = "inflation_shock_2022"
        r = call("stress_test", scenario=scenario)
        if (err := fail(r)):
            return err, trace
        b, s = r["baseline"], r["stressed"]
        outcome = ("your savings would still last to the end of the plan" if s["funded"]
                   else f"your savings would run short in {s['first_shortfall_year']}")
        return (f"**{r['name']}** (replayed starting in {r['starts_in']})\n\n"
                f"If this happened again, {outcome}. Money left at the end would be about "
                f"{_money(s['ending_portfolio_real'])} instead of {_money(b['ending_portfolio_real'])} "
                f"(today's dollars).\n\n"
                "This replays what actually happened in the past. It is not a prediction."), trace

    age = re.search(r"\b(5\d|6\d|7\d|8[0-5])\b", text)
    num = re.search(r"(\d+(?:\.\d+)?)", text)
    if "social security" in text or re.search(r"\bclaim", text):
        claim = int(age.group(1)) if age and 62 <= int(age.group(1)) <= 70 else 70
        r = call("run_what_if", ss_claim_age=claim)
        return fail(r) or _what_if_text(f"What if Social Security starts at {claim}?", r), trace

    if "retire" in text:
        if age and "year" not in text.split(age.group(1))[-1][:8]:
            r = call("run_what_if", retirement_age=int(age.group(1)))
            return fail(r) or _what_if_text(f"What if you retire at {age.group(1)}?", r), trace
        years = int(float(num.group(1))) if num else 2
        years = -years if re.search(r"earlier|sooner|early", text) else years
        r = call("run_what_if", retire_years_later=years)
        label = f"What if you retire {abs(years)} year{'s' if abs(years) != 1 else ''} {'later' if years > 0 else 'earlier'}?"
        return fail(r) or _what_if_text(label, r), trace

    if re.search(r"spend|spending|budget|expenses|cut back", text):
        pct = float(num.group(1)) if num else 10.0
        pct = pct if re.search(r"more|increase|extra|raise", text) else -pct
        r = call("run_what_if", spending_change_pct=pct)
        label = f"What if you spend {abs(pct):g}% {'more' if pct > 0 else 'less'}?"
        return fail(r) or _what_if_text(label, r), trace

    if re.search(r"return|market.*(lower|worse|less)|grow", text) and num:
        pts = -abs(float(num.group(1)))
        r = call("run_what_if", return_change_pct=pts)
        return fail(r) or _what_if_text(f"What if investments earn {abs(pts):g} percentage points less each year?", r), trace

    year = re.search(r"\b(20[2-9]\d)\b", text)
    if year:
        r = call("yearly_details", year=int(year.group(1)))
        if (err := fail(r)):
            return err, trace
        k = r["price_index"]
        return (f"**{r['year']}** in the average-return projection (today's dollars):\n\n"
                f"- Income: pay {_money(r['wages'] / k)}, Social Security {_money(r['social_security'] / k)}, "
                f"other {_money(r['other_income'] / k)}\n"
                f"- Spending: {_money(r['spending_total'] / k)}\n"
                f"- Taxes: {_money(r['tax_total'] / k)}\n"
                f"- Taken from savings: {_money(r['withdrawals_total'] / k)}\n"
                f"- Investments at year end: {_money(r['portfolio'] / k)}"), trace

    if re.search(r"tax", text):
        r = call("get_plan_overview")
        if (err := fail(r)):
            return err, trace
        return (f"Over the whole plan you are projected to pay about "
                f"**{_money(r['results']['lifetime_taxes_todays_dollars'])}** in taxes (today's dollars). "
                f"The Taxes page shows this year by year, and compares ways to lower it, such as changing the "
                f"order you draw from accounts or doing Roth conversions."), trace

    r = call("get_plan_overview")
    if (err := fail(r)):
        return (f"{err}\n\nOnce you have added the people in your household, your accounts and your spending, "
                f"I can tell you whether you are on track."), trace
    reply = _baseline_text(r["results"])
    if not re.search(r"track|enough|run out|last|ok|okay|safe|how am i|doing|summary|overview", text):
        reply = ("I am the built-in helper, so I understand a limited set of questions. Here is where your plan "
                 "stands:\n\n" + reply + "\n\nYou can ask things like: " + "; ".join(SUGGESTIONS[1:6]) + ".")
    return reply, trace


# ----------------------------------------------------------------------------- live mode


def _history(conv: AIConversation) -> list[dict]:
    out: list[dict] = []
    for m in conv.messages[-MAX_HISTORY:]:
        if m.role == "tool":
            out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
        elif m.role == "assistant" and m.tool_calls:
            out.append({"role": "assistant", "content": m.content or None, "tool_calls": [
                {"id": c["id"], "type": "function",
                 "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}} for c in m.tool_calls]})
        else:
            out.append({"role": m.role, "content": m.content})
    while out and out[0]["role"] == "tool":  # never start with an orphaned tool result
        out.pop(0)
    return out


def _live(ctx: Ctx, conv: AIConversation, add) -> tuple[str, list[dict]]:
    provider = ChatProvider(get_settings())
    trace: list[dict] = []
    for _ in range(MAX_TOOL_ROUNDS):
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + _history(conv)
        result = provider.complete(messages, tools.TOOL_SPECS)
        if not result["tool_calls"]:
            return result["content"] or "I could not produce an answer. Please try rephrasing.", trace
        add("assistant", result["content"], tool_calls=result["tool_calls"])
        for call in result["tool_calls"]:
            out = tools.execute(ctx, conv.id, call["name"], call["arguments"])
            trace.append({"name": call["name"], "arguments": call["arguments"], "result": out})
            add("tool", json.dumps(out, default=str), tool_call_id=call["id"], tool_name=call["name"])
    return ("I needed too many steps to answer that. Could you ask a narrower question?"), trace


# ----------------------------------------------------------------------------- entry point


def chat(ctx: Ctx, conversation_id: str | None, message: str) -> dict:
    st = status(ctx)
    if conversation_id:
        conv = ctx.owned(AIConversation, conversation_id)
    else:
        conv = AIConversation(household_id=ctx.hid, user_id=ctx.user.id, title=message[:80], mode=st["mode"],
                              model=st["model"])
        ctx.db.add(conv)
        ctx.db.flush()
    seq = len(conv.messages)

    def add(role: str, content: str, **kw) -> AIMessage:
        nonlocal seq
        msg = AIMessage(household_id=ctx.hid, conversation_id=conv.id, seq=seq, role=role, content=content, **kw)
        seq += 1
        conv.messages.append(msg)
        ctx.db.flush()
        return msg

    add("user", message)
    mode = st["mode"]
    notice = None
    if mode == "live":
        try:
            reply, trace = _live(ctx, conv, add)
        except LLMError as exc:
            mode = "demo"
            notice = f"{exc} The built-in helper answered instead."
            reply, trace = _demo(ctx, conv.id, message)
    else:
        reply, trace = _demo(ctx, conv.id, message)
    add("assistant", reply)
    ctx.log("ai.chat", "ai_conversation", conv.id, {"mode": mode, "tools": [t["name"] for t in trace]})
    proposals = list(ctx.db.scalars(select(AIProposal).where(
        AIProposal.conversation_id == conv.id, AIProposal.status == "pending")))
    return {
        "conversation_id": conv.id,
        "mode": mode,
        "notice": notice,
        "reply": reply,
        "tools_used": [{"name": t["name"], "arguments": t["arguments"]} for t in trace],
        "proposals": [proposal_out(p) for p in proposals],
        "disclaimer": "Estimates based on your inputs and assumptions - not guarantees and not advice.",
    }


def proposal_out(p: AIProposal) -> dict:
    return {"id": p.id, "title": p.title, "explanation": p.explanation, "change": p.change, "status": p.status,
            "created_at": p.created_at.isoformat()}


def glossary_terms() -> list[str]:
    return sorted(v["term"] for v in GLOSSARY.values())
