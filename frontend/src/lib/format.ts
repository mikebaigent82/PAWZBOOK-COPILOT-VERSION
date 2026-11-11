export function money(value: number | null | undefined, opts: { compact?: boolean } = {}): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  if (opts.compact && Math.abs(value) >= 10000) {
    const abs = Math.abs(value);
    const sign = value < 0 ? "-" : "";
    if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(abs >= 1e7 ? 1 : 2)}M`;
    return `${sign}$${Math.round(abs / 1000)}k`;
  }
  return value.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

export function pct(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${(value * 100).toFixed(digits)}%`;
}

export function signedMoney(value: number): string {
  if (Math.abs(value) < 0.5) return "no change";
  return `${value > 0 ? "+" : "-"}${money(Math.abs(value))}`;
}

export function signedPoints(value: number): string {
  const pts = Math.round(value * 100);
  if (pts === 0) return "no change";
  return `${pts > 0 ? "+" : ""}${pts} point${Math.abs(pts) === 1 ? "" : "s"}`;
}

export function dateText(iso: string | null | undefined): string {
  if (!iso) return "not recorded";
  return new Date(iso).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

export const TAX_TYPE_LABEL: Record<string, string> = {
  cash: "Bank / savings",
  taxable: "Taxable investments (brokerage)",
  traditional: "Pre-tax retirement (401k / IRA)",
  roth: "Roth (tax-free)",
  hsa: "Health savings (HSA)",
};

export const TAX_TYPE_SHORT: Record<string, string> = {
  cash: "Savings",
  taxable: "Taxable",
  traditional: "Pre-tax",
  roth: "Roth",
  hsa: "HSA",
};

export const TAX_TYPE_HELP: Record<string, string> = {
  cash: "Checking, savings, CDs, money market.",
  taxable: "A normal investment account. Taxed on interest, dividends and profits when you sell.",
  traditional: "401(k), 403(b), traditional IRA. No tax paid yet; taxed when you take money out.",
  roth: "Roth IRA or Roth 401(k). Already taxed; comes out tax-free in retirement.",
  hsa: "Health savings account. Tax-free for medical costs.",
};

export const TAX_TYPE_COLOR: Record<string, string> = {
  cash: "#8aa39b",
  taxable: "#3a7ca5",
  traditional: "#1b6b58",
  roth: "#c98f1f",
  hsa: "#8f5fa0",
};

export const CLASS_COLOR: Record<string, string> = {
  us_stocks: "#1b6b58",
  intl_stocks: "#3a7ca5",
  bonds: "#c98f1f",
  cash: "#8aa39b",
  real_estate: "#8f5fa0",
  other: "#a0a6a3",
};
