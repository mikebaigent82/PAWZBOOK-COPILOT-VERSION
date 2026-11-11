"""Reports in PDF, Excel and CSV. Every report states when it was produced,
which assumptions and rule versions it used, how fresh the data is, and that
it is an estimate rather than advice."""
from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

import pandas as pd
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..engine import models as em

DISCLAIMER = (
    "This report is an estimate produced from the information and assumptions you entered. Projections are "
    "hypothetical, are not guarantees of future results, and are not financial, tax, investment or legal advice. "
    "Tax calculations are simplified. Consider speaking with a qualified professional before making decisions."
)

YEAR_COLUMNS = [
    ("year", "Year"), ("wages", "Pay"), ("social_security", "Social Security"), ("other_income", "Other income"),
    ("spending_total", "Spending"), ("tax_total", "Taxes"), ("withdrawals_total", "Withdrawals"),
    ("rmd", "Required withdrawals"), ("roth_conversion", "Roth conversion"), ("portfolio", "Investments (end)"),
    ("net_worth", "Net worth (end)"), ("shortfall", "Shortfall"),
]


def assumption_rows(plan: em.PlanInput, meta: dict) -> list[tuple[str, str]]:
    a = plan.assumptions
    rc = a.roth_conversion
    conv = {"none": "None", "fixed": f"${rc.amount:,.0f} per year",
            "fill_bracket": f"Fill the {rc.bracket_rate:.0%} bracket",
            "fill_magi": f"Up to income of ${rc.amount:,.0f}"}[rc.mode]
    if rc.mode != "none":
        conv += f" ({rc.start_year or plan.start_year}-{rc.end_year or plan.end_year})"
    rows = [
        ("Plan period", f"{plan.start_year} to {plan.end_year}"),
        ("Tax filing status", {"single": "Single", "mfj": "Married filing jointly"}[plan.filing_status]),
        ("Inflation", f"{a.inflation:.2%} per year"),
        ("Healthcare inflation", f"{a.healthcare_inflation:.2%} per year"),
        ("State income tax", f"{a.state_tax.state}: {a.state_tax.rate:.2%} effective rate (simplified)"),
        ("Withdrawal order", a.withdrawal_strategy.replace("_", " ")),
        ("Roth conversions", conv),
        ("Spending guardrails", "On" if a.guardrails.enabled else "Off"),
        ("Spending after first death", f"{a.survivor_expense_pct:.0%} of before"),
        ("Tax rule versions", ", ".join(meta.get("tax_rule_versions", []))),
        ("Engine version", meta.get("engine_version", "")),
        ("Input fingerprint", meta.get("plan_hash", "")[:16]),
    ]
    for m in plan.members:
        rows.append((f"{m.name}", f"born {m.birth_year}, retires at {m.retirement_age}, plan to age "
                                  f"{m.life_expectancy}, Social Security from {m.social_security.claim_age}"))
    for c in plan.asset_classes:
        rows.append((f"Return: {c.name}", f"{c.expected_return:.2%} average, {c.volatility:.2%} volatility"))
    return rows


def _year_table(projection: dict, real: bool) -> list[list]:
    out = [[label for _, label in YEAR_COLUMNS]]
    for r in projection["rows"]:
        k = r["price_index"] if real else 1.0
        out.append([r["year"]] + [round(r[key] / k) for key, _ in YEAR_COLUMNS[1:]])
    return out


def build_csv(projection: dict) -> bytes:
    buf = io.StringIO()
    buf.write(f"# Year-by-year projection. Amounts in nominal (future) dollars. Generated "
              f"{datetime.now(UTC):%Y-%m-%d %H:%M} UTC. Input fingerprint {projection['meta']['plan_hash'][:16]}.\n")
    buf.write("# Estimates only - not a guarantee and not advice.\n")
    rows = projection["rows"]
    keys = [k for k in rows[0] if k not in ("ages",)]
    w = csv.writer(buf)
    w.writerow(keys)
    for r in rows:
        w.writerow([r[k] for k in keys])
    return buf.getvalue().encode()


def build_xlsx(plan: em.PlanInput, projection: dict, mc: dict | None, freshness: list[dict],
               insights: dict) -> bytes:
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    s = projection["summary"]
    summary = [("Report generated", generated), ("Plan", plan.name), ("Headline", insights["headline"])]
    summary += [(p["kind"].title(), p["text"]) for p in insights["points"]]
    summary += [(k.replace("_", " ").capitalize(), v) for k, v in s.items()]
    summary.append(("Important", DISCLAIMER))
    rows = projection["rows"]
    year_df = pd.DataFrame([{k: v for k, v in r.items() if k != "ages"} for r in rows])
    real_df = year_df.copy()
    skip = {"year", "filing_status", "price_index", "marginal_rate", "spending_multiplier", "withdrawal_rate",
            "portfolio_return"}
    for col in real_df.columns:
        if col not in skip:
            real_df[col] = (real_df[col] / real_df["price_index"]).round(2)
    accounts_df = pd.DataFrame({"year": projection["years"],
                                **{f"{a['name']} ({a['tax_type']})": a["balances"] for a in projection["accounts"]}})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame(summary, columns=["Item", "Value"]).to_excel(xw, sheet_name="Summary", index=False)
        pd.DataFrame(assumption_rows(plan, projection["meta"]), columns=["Assumption", "Value"]).to_excel(
            xw, sheet_name="Assumptions", index=False)
        year_df.to_excel(xw, sheet_name="Yearly (future dollars)", index=False)
        real_df.to_excel(xw, sheet_name="Yearly (today's dollars)", index=False)
        accounts_df.to_excel(xw, sheet_name="Accounts (future dollars)", index=False)
        if mc:
            mc_df = pd.DataFrame({"year": mc["years"],
                                  **{f"investments_real_{k}": v for k, v in mc["portfolio_real"].items()},
                                  "cumulative_failure_probability": mc["cumulative_failure_probability"]})
            mc_df.to_excel(xw, sheet_name="Chance of success", index=False)
            meta = [(k, str(v)) for k, v in mc["meta"].items()]
            meta.insert(0, ("success_probability", mc["success_probability"]))
            pd.DataFrame(meta, columns=["Item", "Value"]).to_excel(xw, sheet_name="Simulation details", index=False)
        pd.DataFrame(freshness or [{"item": "No accounts", "as_of": "", "source": ""}]).to_excel(
            xw, sheet_name="Data freshness", index=False)
        for ws in xw.book.worksheets:
            ws.column_dimensions["A"].width = 34
            ws.column_dimensions["B"].width = 60 if ws.title in ("Summary", "Assumptions") else 18
    return buf.getvalue()


def _chart(projection: dict) -> Drawing:
    years = projection["years"]
    nominal = [r["portfolio"] for r in projection["rows"]]
    real = [r["portfolio"] / r["price_index"] for r in projection["rows"]]
    d = Drawing(6.8 * inch, 2.9 * inch)
    lp = LinePlot()
    lp.x, lp.y, lp.width, lp.height = 60, 35, 6.8 * inch - 90, 2.9 * inch - 70
    lp.data = [list(zip(years, real)), list(zip(years, nominal))]
    lp.lines[0].strokeColor = colors.HexColor("#1f6f5c")
    lp.lines[0].strokeWidth = 2
    lp.lines[1].strokeColor = colors.HexColor("#9aa5b1")
    lp.lines[1].strokeWidth = 1.2
    lp.xValueAxis.valueMin, lp.xValueAxis.valueMax = years[0], years[-1]
    lp.xValueAxis.valueStep = max(1, (years[-1] - years[0]) // 8)
    lp.xValueAxis.labelTextFormat = "%d"
    lp.yValueAxis.valueMin = 0
    lp.yValueAxis.labelTextFormat = lambda v: f"${v / 1000:,.0f}k"
    d.add(lp)
    d.add(String(60, 2.9 * inch - 18, "Investments: today's dollars (green) and future dollars (grey)",
                 fontSize=9, fillColor=colors.HexColor("#333333")))
    return d


def build_pdf(plan: em.PlanInput, projection: dict, mc: dict | None, freshness: list[dict],
              insights: dict, app_name: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                            topMargin=0.7 * inch, bottomMargin=0.7 * inch, title=f"{plan.name} - retirement plan")
    st = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=st["BodyText"], fontSize=10.5, leading=15)
    small = ParagraphStyle("small", parent=st["BodyText"], fontSize=8.5, leading=11, textColor=colors.HexColor("#555555"))
    h2 = ParagraphStyle("h2", parent=st["Heading2"], textColor=colors.HexColor("#1f4e46"), spaceBefore=12)
    generated = datetime.now(UTC).strftime("%B %d, %Y at %H:%M UTC")
    grid = TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f1ee")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9f8")]),
    ])

    el: list = [
        Paragraph(f"{plan.name}", st["Title"]),
        Paragraph(f"Retirement plan summary &nbsp;|&nbsp; prepared with {app_name} &nbsp;|&nbsp; {generated}", small),
        Spacer(1, 10),
        Paragraph(f"<b>{insights['headline']}</b>", ParagraphStyle("lead", parent=body, fontSize=14, leading=18)),
        Spacer(1, 4),
    ]
    for p in insights["points"]:
        el.append(Paragraph("&bull; " + p["text"], body))
    el += [Spacer(1, 8), Paragraph(DISCLAIMER, small), Paragraph("Your investments over time", h2), _chart(projection)]
    el.append(Paragraph(
        "Based on the average-return projection. \"Today's dollars\" removes the effect of rising prices.", small))

    if mc:
        el.append(Paragraph("Chance of success", h2))
        m = mc["meta"]
        el.append(Paragraph(
            f"Your plan was tested in {mc['n_paths']:,} simulated futures. It succeeded in "
            f"<b>{mc['success_probability']:.0%}</b> of them. In today's dollars, investments at the end of the "
            f"plan ranged from ${mc['ending_portfolio_real']['p10']:,.0f} (poor markets, 10th percentile) to "
            f"${mc['ending_portfolio_real']['p90']:,.0f} (strong markets, 90th percentile), with a middle outcome "
            f"of ${mc['ending_portfolio_real']['p50']:,.0f}.", body))
        el.append(Paragraph(
            f"Simulation details: seed {m['seed']}, {m['distribution']} returns, NumPy {m['numpy_version']}, "
            f"engine {m['engine_version']}. The same inputs and seed always reproduce these numbers.", small))

    el.append(Paragraph("Assumptions used", h2))
    t = Table([["Assumption", "Value"]] + [list(r) for r in assumption_rows(plan, projection["meta"])],
              colWidths=[2.3 * inch, 4.6 * inch], repeatRows=1)
    t.setStyle(grid)
    el.append(t)

    el.append(Paragraph("How fresh is the data?", h2))
    fresh = [["Item", "Value as of", "Source"]] + [[f["item"], f["as_of"] or "not recorded", f["source"]]
                                                   for f in freshness] if freshness else [["No accounts entered", "", ""]]
    t = Table(fresh, colWidths=[3.3 * inch, 1.6 * inch, 2.0 * inch], repeatRows=1)
    t.setStyle(grid)
    el.append(t)

    notes = projection.get("warnings", []) + projection.get("notes", [])
    if notes:
        el.append(Paragraph("Notes", h2))
        for n in notes:
            el.append(Paragraph("&bull; " + n, body))

    el.append(PageBreak())
    el.append(Paragraph("Year by year (today's dollars, rounded)", h2))
    table = _year_table(projection, real=True)
    widths = [0.45 * inch] + [0.6 * inch] * (len(YEAR_COLUMNS) - 1)
    hdr = ParagraphStyle("hdr", parent=small, fontSize=6.5, leading=7.5, textColor=colors.black)
    data = [[Paragraph(c, hdr) for c in table[0]]] + [[r[0]] + [f"{v:,.0f}" for v in r[1:]] for r in table[1:]]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle(list(grid.getCommands()) + [("FONTSIZE", (0, 1), (-1, -1), 7),
                                                       ("ALIGN", (1, 1), (-1, -1), "RIGHT")]))
    el.append(t)
    el += [Spacer(1, 8), Paragraph(
        "Method: all cash flows are assumed to happen at the start of each year; investment returns are applied "
        "afterwards. Federal tax follows the published rate schedules for the listed rule versions, indexed for "
        "inflation in later years. State tax uses one simplified effective rate. " + DISCLAIMER, small)]

    def footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(0.75 * inch, 0.45 * inch, f"{app_name} - estimates only, not advice - {generated}")
        canvas.drawRightString(letter[0] - 0.75 * inch, 0.45 * inch, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    doc.build(el, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
