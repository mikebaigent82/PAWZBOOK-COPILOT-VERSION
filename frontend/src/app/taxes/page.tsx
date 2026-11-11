"use client";

import { useEffect, useState } from "react";
import { SimpleLines } from "@/components/charts";
import { AssumptionLine, Badge, Button, Card, ErrorBox, Help, Loading, Notice, PageHeader, Select, Stat, Table } from "@/components/ui";
import { api } from "@/lib/api";
import { money, pct, signedMoney } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { PlanInfo, Projection } from "@/lib/types";

interface Metrics {
  lifetime_taxes_real: number;
  lifetime_medicare_premiums_real: number;
  lifetime_cost: number;
  after_tax_wealth: number;
  beneficiary_value: number;
  ending_portfolio_real: number;
  total_converted_nominal: number;
  max_marginal_rate: number;
  funded: boolean;
}

interface Candidate {
  key: string;
  label: string;
  conversion?: Record<string, unknown>;
  metrics: Metrics;
  score: number;
  pareto_efficient: boolean;
  vs_baseline?: { lifetime_cost: number; after_tax_wealth: number; beneficiary_value: number };
  conversions_by_year?: number[];
  current?: boolean;
}

interface RothResult {
  id: string;
  recommended_key: string;
  window: [number, number] | null;
  candidates: Candidate[];
  years: number[];
  method: string;
  limitations: string[];
  current_conversion: { mode: string };
}

const GOALS = [
  { value: "balanced", label: "A balance of all three", w: { lifetime_cost: 1, after_tax_wealth: 1, beneficiary_value: 1 } },
  { value: "tax", label: "Pay the least tax over my lifetime", w: { lifetime_cost: 1, after_tax_wealth: 0, beneficiary_value: 0 } },
  { value: "wealth", label: "Have the most to spend myself", w: { lifetime_cost: 0, after_tax_wealth: 1, beneficiary_value: 0 } },
  { value: "heirs", label: "Leave the most to my family", w: { lifetime_cost: 0, after_tax_wealth: 0, beneficiary_value: 1 } },
];

export default function Taxes() {
  const plan = useApi<PlanInfo>("/plan");
  const [proj, setProj] = useState<Projection | null>(null);
  const [goal, setGoal] = useState("balanced");
  const [roth, setRoth] = useState<RothResult | null>(null);
  const [order, setOrder] = useState<{ recommended_key: string; candidates: Candidate[] } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function load(g = goal) {
    setBusy("load");
    setError(null);
    try {
      const w = GOALS.find((x) => x.value === g)!.w;
      const [p, r, o] = await Promise.all([
        api.post<Projection>("/projection"),
        api.post<RothResult>("/roth/optimize", { weights: w }),
        api.post<{ recommended_key: string; candidates: Candidate[] }>("/withdrawal-strategies/compare"),
      ]);
      setProj(p);
      setRoth(r);
      setOrder(o);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function applyRoth(key: string, label: string) {
    if (!roth || !window.confirm(`Save "${label}" into your plan? You can change it back at any time.`)) return;
    setBusy(key);
    try {
      await api.post("/roth/apply", { strategy_id: roth.id, key });
      setMessage(`Saved: ${label}. Your plan now includes this.`);
      plan.reload();
      await load();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  }

  async function applyOrder(key: string, label: string) {
    if (!window.confirm(`Use "${label}" as your withdrawal order?`)) return;
    setBusy(key);
    try {
      await api.patch("/plan/assumptions", { changes: { withdrawal_strategy: key }, note: `Withdrawal order: ${label}` });
      setMessage(`Saved: ${label}.`);
      plan.reload();
      await load();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  }

  const currentMode = plan.data?.assumptions.roth_conversion.mode;
  const s = proj?.summary;

  return (
    <>
      <PageHeader title="Taxes" intro="How much tax your plan pays, and ways that might lower it. Nothing changes until you choose to save an option." />
      {busy === "load" && !roth && <Loading label="Comparing tax strategies (this takes a few seconds)..." />}
      <ErrorBox error={error} />
      {message && <Notice tone="good" className="mb-4">{message}</Notice>}

      {proj && s && (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Lifetime taxes" value={money(s.lifetime_taxes_real)} sub="today's dollars" />
            <Stat label="Medicare premiums" value={money(s.lifetime_medicare_premiums_real)} sub="today's dollars, lifetime"
              help="Medicare Part B and D premiums from age 65, including any income-based surcharge (IRMAA), which depends on your income two years earlier." />
            <Stat label="Highest tax bracket reached" value={pct(s.max_marginal_rate)} help="The federal rate on your last dollar of income in your highest-income year." />
            <Stat label="Roth conversions in plan" value={currentMode && currentMode !== "none" ? money(s.total_roth_conversions_nominal) : "None"} sub={currentMode && currentMode !== "none" ? "future dollars, total" : undefined} />
          </div>
          <Card title="Taxes each year" subtitle="Today's dollars, average-return projection." className="mb-6">
            <SimpleLines
              data={proj.rows.map((r) => ({
                year: r.year,
                fed: (Number(r.tax_federal_ordinary) + Number(r.tax_federal_ltcg) + Number(r.tax_niit)) / r.price_index,
                state: Number(r.tax_state) / r.price_index,
                payroll: Number(r.tax_payroll) / r.price_index,
                medicare: Number(r.medicare_premiums) / r.price_index,
              }))}
              lines={[
                { key: "fed", label: "Federal income tax", color: "#1b6b58" },
                { key: "state", label: "State income tax", color: "#3a7ca5" },
                { key: "payroll", label: "Payroll tax", color: "#8f5fa0" },
                { key: "medicare", label: "Medicare premiums", color: "#c98f1f", dashed: true },
              ]}
            />
            <AssumptionLine>
              Federal tax uses the IRS schedules for {proj.meta.tax_rule_versions.join(", ")}, raised with inflation in later years. The senior deduction ends after 2028 as current law says.
              State tax is a simple average rate ({pct(plan.data?.assumptions.state_tax.rate ?? 0, 1)} for {plan.data?.assumptions.state_tax.state}).
            </AssumptionLine>
          </Card>
        </>
      )}

      {roth && (
        <Card
          className="mb-6"
          title={<>Roth conversions<Help text="Moving money from a pre-tax account (401k/IRA) into a Roth account. You pay income tax on it now, so it grows and comes out tax-free later, and it lowers required withdrawals. It tends to help when your tax rate now is lower than it will be later." /></>}
          subtitle={roth.window ? `The usual window is ${roth.window[0]}-${roth.window[1]}: after retiring and before required withdrawals start.` : undefined}
          actions={
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted">What matters most?</span>
              <Select value={goal} onChange={(v) => { setGoal(v); load(v); }} options={GOALS.map((g) => ({ value: g.value, label: g.label }))} />
            </div>
          }
        >
          {roth.candidates.length === 1 ? (
            <Notice tone="info">There is no pre-tax money to convert in your plan, so Roth conversions do not apply.</Notice>
          ) : (() => {
            const best = roth.candidates.find((c) => c.key === roth.recommended_key)!;
            return (
              <>
                <Notice tone={best.key === "none" ? "info" : "good"} title={best.key === "none" ? "Doing nothing scored best for this goal" : `Best for this goal: ${best.label}`}>
                  {best.key !== "none" && best.vs_baseline && (
                    <>Compared with no conversions: lifetime tax and Medicare cost {signedMoney(best.vs_baseline.lifetime_cost)}, money you keep after tax {signedMoney(best.vs_baseline.after_tax_wealth)}, value to heirs {signedMoney(best.vs_baseline.beneficiary_value)} (today&apos;s dollars).</>
                  )}
                </Notice>
                <Table
                  className="mt-4"
                  numericFrom={1}
                  head={["Option", "Tax + Medicare", "Kept after tax", "Value to heirs", "Amount converted", "Score", ""]}
                  rows={roth.candidates.map((c) => [
                    <span key="l">{c.label} {c.key === roth.recommended_key && <Badge tone="good">best</Badge>} {c.pareto_efficient && c.key !== roth.recommended_key && <Badge>good trade-off</Badge>}</span>,
                    c.key === "none" ? money(c.metrics.lifetime_cost) : signedMoney(c.vs_baseline!.lifetime_cost),
                    c.key === "none" ? money(c.metrics.after_tax_wealth) : signedMoney(c.vs_baseline!.after_tax_wealth),
                    c.key === "none" ? money(c.metrics.beneficiary_value) : signedMoney(c.vs_baseline!.beneficiary_value),
                    money(c.metrics.total_converted_nominal),
                    Math.round(c.score),
                    <Button key="a" variant="ghost" className="min-h-8 px-2 text-sm" busy={busy === c.key} onClick={() => applyRoth(c.key, c.label)}>Use this</Button>,
                  ])}
                />
                <p className="mt-2 text-xs text-muted">The first row shows totals with no conversions; the other rows show the change from that. All in today&apos;s dollars, except amount converted (future dollars). &quot;Good trade-off&quot; means no other option is better on all three measures.</p>
                <details className="mt-3 text-sm text-muted">
                  <summary className="cursor-pointer font-medium text-ink">How this is worked out</summary>
                  <p className="mt-2">{roth.method}</p>
                  <ul className="mt-1 list-disc pl-5">{roth.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
                </details>
              </>
            );
          })()}
        </Card>
      )}

      {order && (
        <Card title={<>Which accounts to spend from first<Help text="In retirement you can take money from savings, taxable investments, pre-tax accounts or Roth accounts. The order changes how much tax you pay each year." /></>}>
          <Table
            numericFrom={1}
            head={["Order", "Tax + Medicare", "Left at end", "Value to heirs", ""]}
            rows={order.candidates.map((c) => [
              <span key="l">{c.label} {c.current && <Badge tone="brand">current</Badge>} {c.key === order.recommended_key && <Badge tone="good">best overall</Badge>}</span>,
              money(c.metrics.lifetime_cost), money(c.metrics.ending_portfolio_real), money(c.metrics.beneficiary_value),
              c.current ? "" : <Button key="a" variant="ghost" className="min-h-8 px-2 text-sm" busy={busy === c.key} onClick={() => applyOrder(c.key, c.label)}>Use this</Button>,
            ])}
          />
          <p className="mt-2 text-xs text-muted">Today&apos;s dollars, average-return projection, with your current Roth conversion setting.</p>
        </Card>
      )}
    </>
  );
}
