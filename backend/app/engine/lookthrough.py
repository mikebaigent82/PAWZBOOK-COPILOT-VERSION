"""Portfolio analytics and look-through.

"Look-through" means seeing what a fund actually holds. A holding with
composition data (for example a balanced fund that is 60% stocks / 40% bonds,
or a fund's list of underlying companies) is split into its parts before
exposures are added up. Holdings without composition data are counted as a
single position in their own asset class, and are listed so the user knows
where look-through was not possible.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SINGLE_POSITION_LIMIT = 0.10   # flag any one underlying security above 10% of the portfolio
TOP5_LIMIT = 0.50              # flag when the five largest positions exceed 50%
ASSET_CLASS_LIMIT = 0.90       # flag when one asset class exceeds 90%


class CompositionPart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["asset_class", "security", "sector"]
    key: str
    name: str | None = None
    weight: float = Field(ge=0, le=1)


class HoldingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str
    account_name: str
    tax_type: str
    symbol: str | None = None
    name: str
    value: float = Field(ge=0)
    asset_class: str = "other"
    is_fund: bool = False
    composition: list[CompositionPart] = []
    composition_source: str | None = None
    composition_as_of: str | None = None


def _split(holding: HoldingInput, kind: str) -> list[tuple[str, str, float]] | None:
    """Parts of a holding for one composition kind, as (key, name, value).
    Any weight not covered by the composition is reported as 'unclassified'."""
    parts = [p for p in holding.composition if p.kind == kind]
    if not parts:
        return None
    covered = sum(p.weight for p in parts)
    scale = 1.0 / covered if covered > 1.0 else 1.0
    out = [(p.key, p.name or p.key, holding.value * p.weight * scale) for p in parts]
    if covered < 1.0 - 1e-9:
        label = "Other holdings of " + (holding.symbol or holding.name)
        out.append((f"_rest:{holding.symbol or holding.name}", label, holding.value * (1.0 - covered)))
    return out


def asset_class_weights(holdings: list[HoldingInput]) -> dict[str, float]:
    """Asset-class weights of a group of holdings, with look-through. Sums to 1."""
    total = sum(h.value for h in holdings)
    if total <= 0:
        return {}
    acc: dict[str, float] = defaultdict(float)
    for h in holdings:
        parts = _split(h, "asset_class")
        if parts is None:
            acc[h.asset_class] += h.value
        else:
            for key, _, value in parts:
                acc[h.asset_class if key.startswith("_rest:") else key] += value
    return {k: v / total for k, v in acc.items()}


def analyze(holdings: list[HoldingInput], asset_class_names: dict[str, str] | None = None) -> dict:
    names = asset_class_names or {}
    total = sum(h.value for h in holdings)
    if total <= 0:
        return {"total_value": 0.0, "by_asset_class": [], "by_tax_type": [], "by_account": [],
                "positions": [], "sectors": [], "concentration": {"flags": [], "hhi": 0.0, "top5_share": 0.0},
                "look_through": {"covered_value": 0.0, "covered_share": 0.0, "not_covered": []}}

    by_class: dict[str, float] = defaultdict(float)
    by_tax: dict[str, float] = defaultdict(float)
    by_account: dict[str, dict] = {}
    positions: dict[str, dict] = {}
    sectors: dict[str, float] = defaultdict(float)
    covered = 0.0
    not_covered = []

    for h in holdings:
        by_tax[h.tax_type] += h.value
        acct = by_account.setdefault(h.account_id, {"account_id": h.account_id, "name": h.account_name,
                                                    "tax_type": h.tax_type, "value": 0.0})
        acct["value"] += h.value

        parts = _split(h, "asset_class")
        if parts is None:
            by_class[h.asset_class] += h.value
        else:
            for key, _, value in parts:
                by_class[h.asset_class if key.startswith("_rest:") else key] += value

        sec_parts = _split(h, "security")
        if sec_parts is None:
            key = (h.symbol or h.name).upper()
            pos = positions.setdefault(key, {"key": key, "name": h.name, "value": 0.0, "direct": 0.0,
                                             "through_funds": 0.0, "is_fund": h.is_fund})
            pos["value"] += h.value
            pos["direct"] += h.value
            if h.is_fund and parts is None:
                not_covered.append({"symbol": h.symbol, "name": h.name, "value": round(h.value, 2)})
            elif h.is_fund:
                covered += h.value
        else:
            covered += h.value
            for key, name, value in sec_parts:
                k = key.upper()
                pos = positions.setdefault(k, {"key": k, "name": name, "value": 0.0, "direct": 0.0,
                                               "through_funds": 0.0, "is_fund": key.startswith("_rest:")})
                pos["value"] += value
                pos["through_funds"] += value

        for key, name, value in (_split(h, "sector") or []):
            if not key.startswith("_rest:"):
                sectors[name] += value

    pos_list = sorted(positions.values(), key=lambda p: -p["value"])
    for p in pos_list:
        p["share"] = round(p["value"] / total, 6)
        for k in ("value", "direct", "through_funds"):
            p[k] = round(p[k], 2)
    single = [p for p in pos_list if not p["is_fund"]]
    top5 = sum(p["value"] for p in single[:5]) / total
    hhi = sum((p["value"] / total) ** 2 for p in pos_list)

    flags = []
    for p in single:
        if p["share"] > SINGLE_POSITION_LIMIT:
            flags.append({
                "level": "warning",
                "code": "single_position",
                "message": f"{p['name']} makes up {p['share']:.0%} of your investments "
                           f"(including what your funds hold). More than {SINGLE_POSITION_LIMIT:.0%} in one "
                           f"company is usually considered concentrated.",
            })
    if len(single) >= 5 and top5 > TOP5_LIMIT:
        flags.append({"level": "info", "code": "top5",
                      "message": f"Your five largest individual positions add up to {top5:.0%} of your investments."})
    for key, value in by_class.items():
        if value / total > ASSET_CLASS_LIMIT and key != "cash":
            flags.append({"level": "info", "code": "asset_class",
                          "message": f"{names.get(key, key)} is {value / total:.0%} of your investments. "
                                     f"Spreading money across different kinds of investments lowers risk."})

    def shares(d: dict[str, float], label=lambda k: k) -> list[dict]:
        return [{"key": k, "name": label(k), "value": round(v, 2), "share": round(v / total, 6)}
                for k, v in sorted(d.items(), key=lambda kv: -kv[1])]

    return {
        "total_value": round(total, 2),
        "by_asset_class": shares(by_class, lambda k: names.get(k, k)),
        "by_tax_type": shares(by_tax),
        "by_account": [{**a, "value": round(a["value"], 2), "share": round(a["value"] / total, 6)}
                       for a in sorted(by_account.values(), key=lambda a: -a["value"])],
        "positions": pos_list[:50],
        "sectors": shares(sectors),
        "concentration": {
            "flags": flags,
            "hhi": round(hhi, 6),
            "top5_share": round(top5, 6),
            "limits": {"single_position": SINGLE_POSITION_LIMIT, "top5": TOP5_LIMIT,
                       "asset_class": ASSET_CLASS_LIMIT},
        },
        "look_through": {
            "covered_value": round(covered, 2),
            "covered_share": round(covered / total, 6),
            "not_covered": not_covered,
        },
    }
