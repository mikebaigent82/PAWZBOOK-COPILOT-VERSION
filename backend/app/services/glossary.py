"""Plain-English explanations of the terms used in the app."""
from __future__ import annotations

GLOSSARY: dict[str, dict[str, str]] = {
    "net_worth": {"term": "Net worth", "plain": "Everything you own minus everything you owe."},
    "todays_dollars": {
        "term": "Today's dollars",
        "plain": "Future amounts shown as what they would buy today. Prices rise over time, so $100 in 20 years "
                 "buys less than $100 now. Showing amounts in today's dollars makes them easier to compare.",
    },
    "future_dollars": {
        "term": "Future dollars",
        "plain": "The actual number of dollars in a future year, before adjusting for rising prices.",
    },
    "inflation": {"term": "Inflation", "plain": "How much prices rise each year. At 2.5% a $100 shop costs $102.50 "
                                                "next year."},
    "monte_carlo": {
        "term": "Chance of success (Monte Carlo)",
        "plain": "Nobody knows what markets will do. So we try your plan in 1,000 different made-up futures, "
                 "some good and some bad, and count in how many your money lasts. 85 out of 100 or better is "
                 "generally considered comfortable.",
    },
    "projection": {
        "term": "Average-return projection",
        "plain": "A single year-by-year forecast that assumes every investment earns its expected average "
                 "return every year. Real life is bumpier, which is why we also show the chance of success.",
    },
    "traditional": {
        "term": "Pre-tax account (Traditional 401(k) / IRA)",
        "plain": "Money you have not paid income tax on yet. You pay tax when you take it out.",
    },
    "roth": {
        "term": "Roth account",
        "plain": "Money you already paid tax on. It grows and comes out tax-free in retirement.",
    },
    "taxable": {
        "term": "Taxable (brokerage) account",
        "plain": "A normal investment account. You pay tax each year on interest and dividends, and on profits "
                 "when you sell.",
    },
    "hsa": {"term": "Health savings account (HSA)",
            "plain": "A tax-free account for medical costs."},
    "roth_conversion": {
        "term": "Roth conversion",
        "plain": "Moving money from a pre-tax account to a Roth account. You pay income tax on the amount now, "
                 "so that it can grow and be withdrawn tax-free later. It can pay off in years when your tax "
                 "rate is low.",
    },
    "rmd": {
        "term": "Required minimum distribution (RMD)",
        "plain": "From age 73 or 75 the government requires you to take a minimum amount out of pre-tax "
                 "accounts each year, and pay tax on it.",
    },
    "social_security": {
        "term": "Social Security",
        "plain": "The monthly government retirement payment. You can start between 62 and 70; the longer you "
                 "wait, the larger each payment.",
    },
    "full_retirement_age": {
        "term": "Full retirement age",
        "plain": "The age (66 to 67) at which you get your full Social Security amount. Your statement at "
                 "ssa.gov shows this amount.",
    },
    "guardrails": {
        "term": "Spending guardrails",
        "plain": "A simple rule: if your investments fall a lot, trim optional spending (like travel) a little; "
                 "if they do very well, allow yourself a little more. Essentials are never cut.",
    },
    "essential": {"term": "Essential spending", "plain": "Costs you cannot avoid: housing, food, bills, "
                                                         "insurance, health."},
    "discretionary": {"term": "Optional spending", "plain": "Nice-to-haves you could cut back in a bad year: "
                                                            "travel, hobbies, gifts."},
    "asset_allocation": {
        "term": "Investment mix",
        "plain": "How your money is split between stocks (higher growth, bumpier), bonds (steadier) and cash "
                 "(safest, lowest growth).",
    },
    "look_through": {
        "term": "Look-through",
        "plain": "A fund is a basket of many investments. Look-through opens the basket so you can see what "
                 "you really own in total.",
    },
    "concentration": {
        "term": "Concentration",
        "plain": "Having a lot of your money in one company or one kind of investment. If it does badly, "
                 "it hurts more.",
    },
    "marginal_rate": {"term": "Tax bracket", "plain": "The tax rate on your next dollar of income."},
    "irmaa": {
        "term": "Medicare income surcharge (IRMAA)",
        "plain": "People with higher incomes pay more for Medicare. It is based on your income from two years "
                 "earlier.",
    },
    "stress_test": {
        "term": "Stress test",
        "plain": "Checking how your plan would hold up in a bad stretch, such as a repeat of the 2008 crash.",
    },
    "sequence_risk": {
        "term": "Sequence-of-returns risk",
        "plain": "Bad market years hurt much more right after you retire than later on, because you are "
                 "selling investments to live on while they are down.",
    },
    "volatility": {"term": "Volatility", "plain": "How much an investment's value jumps around from year to year."},
    "cost_basis": {"term": "Cost basis", "plain": "What you originally paid for an investment. You are taxed "
                                                  "only on the profit above it."},
    "withdrawal_strategy": {
        "term": "Withdrawal order",
        "plain": "Which accounts you take money from first in retirement. The order changes how much tax you pay.",
    },
    "seed": {
        "term": "Seed",
        "plain": "A number that fixes the 'made-up futures' so running the same simulation again gives exactly "
                 "the same answer.",
    },
    "filing_status": {"term": "Filing status", "plain": "How you file your tax return: single, or married "
                                                        "filing jointly."},
    "scenario": {"term": "What-if scenario", "plain": "A copy of your plan with one or two things changed, so "
                                                      "you can compare. Your real plan is never altered."},
}


def lookup(term: str) -> dict[str, str] | None:
    key = term.strip().lower().replace(" ", "_").replace("-", "_")
    if key in GLOSSARY:
        return {"key": key, **GLOSSARY[key]}
    for k, v in GLOSSARY.items():
        if key.replace("_", " ") in v["term"].lower() or k in key:
            return {"key": k, **v}
    return None
