"""Plain-English reading of the results. Every sentence is built from numbers
the engine produced; nothing here calculates anything new."""
from __future__ import annotations

from ..engine import models as em

COMFORTABLE = 0.85
WATCH = 0.70
THRESHOLD_NOTE = ("The 85% and 70% lines are common planning rules of thumb, not guarantees. "
                  "You can decide what level of certainty feels right for you.")


def money(x: float) -> str:
    return f"${x:,.0f}"


def status_for(success: float) -> str:
    if success >= COMFORTABLE:
        return "on_track"
    if success >= WATCH:
        return "watch"
    return "at_risk"


def build(plan: em.PlanInput, projection: dict, mc: dict | None) -> dict:
    s = projection["summary"]
    rows = projection["rows"]
    youngest = max(plan.members, key=lambda m: m.birth_year)
    end_age = plan.end_year - youngest.birth_year
    first = rows[0]
    portfolio_now = sum(a.balance for a in plan.accounts)
    points: list[dict] = []

    if mc is not None:
        p = mc["success_probability"]
        status = status_for(p)
        n = mc["n_paths"]
        ok = round(p * n)
        headline = {
            "on_track": "You look on track.",
            "watch": "You are close, but it is worth a look.",
            "at_risk": "Your plan needs attention.",
        }[status]
        points.append({
            "kind": "success",
            "text": f"We tested your plan in {n:,} different possible futures. In {ok:,} of them "
                    f"({p:.0%}) your money lasted through age {end_age}.",
        })
        if mc.get("median_failure_age"):
            points.append({
                "kind": "risk",
                "text": f"In the futures where money ran short, it typically happened around age "
                        f"{mc['median_failure_age']}.",
            })
    else:
        status = "on_track" if s["funded"] else "at_risk"
        headline = "Run the chance-of-success test to see how sturdy your plan is."

    if s["funded"]:
        points.append({
            "kind": "projection",
            "text": f"If investments earn their average return every year, your savings last through age "
                    f"{end_age}, with about {money(s['ending_portfolio_real'])} left over (in today's dollars).",
        })
    else:
        points.append({
            "kind": "projection",
            "text": f"If investments earn their average return every year, your savings would run short in "
                    f"{s['first_shortfall_year']} (around age {s['first_shortfall_age']}).",
        })

    retire_rows = [r for r in rows if r["wages"] == 0]
    if retire_rows:
        r0 = retire_rows[0]
        spend_real = r0["spending_total"] / r0["price_index"]
        guaranteed = (r0["social_security"] + r0["other_income"] + r0["tax_free_income"]) / r0["price_index"]
        later = next((r for r in retire_rows if r["social_security"] > 0), None)
        points.append({
            "kind": "spending",
            "text": f"In your first year of retirement ({r0['year']}) the plan spends about "
                    f"{money(spend_real)} a year in today's dollars.",
        })
        if later:
            g = (later["social_security"] + later["other_income"]) / later["price_index"]
            sp = later["spending_total"] / later["price_index"]
            share = min(g / sp, 1.0) if sp > 0 else 0
            points.append({
                "kind": "income",
                "text": f"Once Social Security starts, guaranteed income covers about {share:.0%} of your "
                        f"spending. The rest comes from your savings.",
            })
        elif guaranteed <= 0:
            points.append({"kind": "income",
                           "text": "No Social Security or pension income has been entered yet."})

    points.append({
        "kind": "tax",
        "text": f"Over the whole plan you are projected to pay about {money(s['lifetime_taxes_real'])} in taxes "
                f"(today's dollars).",
    })

    return {
        "status": status,
        "headline": headline,
        "points": points,
        "numbers": {
            "investments_today": round(portfolio_now, 2),
            "net_worth_end_of_first_year": first["net_worth"],
            "success_probability": mc["success_probability"] if mc else None,
            "plan_end_age": end_age,
            "plan_end_year": plan.end_year,
            "funded_in_projection": s["funded"],
            "ending_portfolio_real": s["ending_portfolio_real"],
            "lifetime_taxes_real": s["lifetime_taxes_real"],
        },
        "thresholds": {"comfortable": COMFORTABLE, "watch": WATCH, "note": THRESHOLD_NOTE},
        "disclaimer": "These are estimates based on your inputs and assumptions. They are not guarantees and "
                      "not financial, tax or legal advice.",
    }
