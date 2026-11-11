"""CSV import so the app is fully usable without connecting any bank account."""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Account, Expense, Holding, Security, Transaction
from .setup import REFERENCE_FUNDS, REFERENCE_SOURCE

MAX_ROWS = 5000
TAX_TYPES = {"cash", "taxable", "traditional", "roth", "hsa"}
TAX_ALIASES = {
    "401k": "traditional", "401(k)": "traditional", "403b": "traditional", "ira": "traditional",
    "traditional ira": "traditional", "pre-tax": "traditional", "pretax": "traditional",
    "roth ira": "roth", "roth 401k": "roth", "brokerage": "taxable", "investment": "taxable",
    "savings": "cash", "checking": "cash", "bank": "cash",
}

TEMPLATES = {
    "accounts": "name,tax_type,balance,cost_basis,institution,annual_contribution\n"
                "Joint brokerage,taxable,150000,90000,Example Brokerage,0\n"
                "My 401(k),traditional,400000,,Example Retirement,12000\n",
    "holdings": "account,tax_type,symbol,name,value,cost_basis,asset_class,quantity\n"
                "Joint brokerage,taxable,VTI,Total US stock market index fund,100000,60000,us_stocks,350\n"
                "Joint brokerage,taxable,BND,Total US bond market index fund,50000,48000,bonds,680\n",
    "transactions": "account,date,kind,symbol,quantity,amount,description\n"
                    "Joint brokerage,2026-01-15,buy,VTI,10,-2900.00,Monthly investment\n",
    "expenses": "name,amount,category,kind\n"
                "Everyday living,48000,essential,living\n"
                "Travel,8000,discretionary,living\n",
}


def number(text: str | None) -> float | None:
    if text is None:
        return None
    t = text.strip()
    if not t:
        return None
    negative = t.startswith("(") and t.endswith(")")
    t = re.sub(r"[,$\s()]", "", t)
    value = float(t)
    return -value if negative else value


def parse_date(text: str) -> date:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"cannot read the date '{text}' (use YYYY-MM-DD)")


def tax_type(text: str | None, default: str = "taxable") -> str:
    t = (text or "").strip().lower()
    if not t:
        return default
    t = TAX_ALIASES.get(t, t)
    if t not in TAX_TYPES:
        raise ValueError(f"unknown account type '{text}' (use cash, taxable, traditional, roth or hsa)")
    return t


def _reader(content: str) -> list[dict[str, str]]:
    content = content.lstrip("﻿")
    rows = list(csv.DictReader(io.StringIO(content)))
    if len(rows) > MAX_ROWS:
        raise ValueError(f"The file has more than {MAX_ROWS:,} rows.")
    return [{(k or "").strip().lower().replace(" ", "_"): (v or "").strip() for k, v in r.items()} for r in rows]


def _account(db: Session, hid: str, name: str, ttype: str | None, cache: dict[str, Account]) -> Account:
    key = name.strip().lower()
    if key in cache:
        return cache[key]
    acct = db.scalar(select(Account).where(Account.household_id == hid, Account.name == name.strip()))
    if acct is None:
        acct = Account(household_id=hid, name=name.strip(), tax_type=tax_type(ttype), source="csv",
                       balance_as_of=date.today())
        db.add(acct)
        db.flush()
    cache[key] = acct
    return acct


def _security(db: Session, hid: str, symbol: str, name: str, asset_class: str | None) -> Security:
    symbol = symbol.strip().upper()
    sec = db.scalar(select(Security).where(Security.household_id == hid, Security.symbol == symbol))
    if sec is None:
        ref = REFERENCE_FUNDS.get(symbol)
        sec = Security(household_id=hid, symbol=symbol, name=name or (ref[0] if ref else symbol),
                       asset_class_key=(asset_class or (ref[1] if ref else "other")).strip().lower(),
                       is_fund=bool(ref))
        if ref:
            sec.composition = [{"kind": "asset_class", "key": k, "weight": w} for k, w in ref[2]]
            sec.composition_source = REFERENCE_SOURCE
            sec.composition_as_of = date.today()
        db.add(sec)
        db.flush()
    return sec


def import_csv(db: Session, hid: str, kind: str, content: str) -> dict:
    """Import rows. Bad rows are skipped and reported; good rows are kept."""
    if kind not in TEMPLATES:
        raise ValueError(f"Unknown import type '{kind}'")
    rows = _reader(content)
    imported, errors = 0, []
    accounts: dict[str, Account] = {}
    touched: set[str] = set()
    for i, r in enumerate(rows, start=2):  # row 1 is the header
        try:
            if not any(r.values()):
                continue
            if kind == "accounts":
                if not r.get("name"):
                    raise ValueError("missing account name")
                acct = _account(db, hid, r["name"], r.get("tax_type"), accounts)
                acct.tax_type = tax_type(r.get("tax_type"), acct.tax_type)
                acct.balance = number(r.get("balance")) or 0.0
                acct.cost_basis = number(r.get("cost_basis"))
                acct.institution = r.get("institution") or acct.institution
                acct.annual_contribution = number(r.get("annual_contribution")) or 0.0
                acct.balance_as_of = date.today()
            elif kind == "holdings":
                if not r.get("account") or not (r.get("symbol") or r.get("name")):
                    raise ValueError("each row needs an account and a symbol or name")
                value = number(r.get("value"))
                if value is None or value < 0:
                    raise ValueError("missing or negative value")
                acct = _account(db, hid, r["account"], r.get("tax_type"), accounts)
                if acct.id not in touched:  # a holdings import replaces that account's holdings
                    for h in list(acct.holdings):
                        db.delete(h)
                    db.flush()
                    touched.add(acct.id)
                symbol = r.get("symbol") or re.sub(r"[^A-Z0-9]", "", r["name"].upper())[:20]
                sec = _security(db, hid, symbol, r.get("name", ""), r.get("asset_class"))
                db.add(Holding(household_id=hid, account_id=acct.id, security_id=sec.id, value=value,
                               cost_basis=number(r.get("cost_basis")), quantity=number(r.get("quantity")),
                               as_of=date.today()))
            elif kind == "transactions":
                if not r.get("account"):
                    raise ValueError("missing account")
                amount = number(r.get("amount"))
                if amount is None:
                    raise ValueError("missing amount")
                acct = _account(db, hid, r["account"], None, accounts)
                db.add(Transaction(household_id=hid, account_id=acct.id, txn_date=parse_date(r.get("date", "")),
                                   kind=(r.get("kind") or "other").lower()[:20], symbol=(r.get("symbol") or None),
                                   quantity=number(r.get("quantity")), amount=amount,
                                   description=(r.get("description") or None), source="csv"))
            elif kind == "expenses":
                amount = number(r.get("amount"))
                if not r.get("name") or amount is None or amount < 0:
                    raise ValueError("each row needs a name and an amount")
                category = (r.get("category") or "essential").lower()
                if category not in ("essential", "discretionary"):
                    raise ValueError("category must be essential or discretionary")
                kind_ = (r.get("kind") or "living").lower()
                db.add(Expense(household_id=hid, name=r["name"], amount=amount, category=category,
                               kind=kind_ if kind_ in ("living", "healthcare", "housing", "one_time", "other")
                               else "living",
                               inflation_mode="healthcare" if kind_ == "healthcare" else "general"))
            imported += 1
        except (ValueError, KeyError) as exc:
            errors.append({"row": i, "message": str(exc)})
    db.flush()
    if kind == "holdings":
        for acct in accounts.values():
            db.refresh(acct)
            acct.balance = sum(float(h.value or 0) for h in acct.holdings)
            acct.balance_as_of = date.today()
    return {"kind": kind, "rows_read": len(rows), "imported": imported, "errors": errors}
