"use client";

import { useEffect, useState } from "react";
import { CashFlowChart, FanChart, Histogram, StackedBalances } from "@/components/charts";
import { AssumptionLine, Button, Card, ErrorBox, Field, Help, Loading, Modal, Notice, NumberInput, PageHeader, Segmented, Select, Stat, Table } from "@/components/ui";
import { api } from "@/lib/api";
import { money, pct, TAX_TYPE_COLOR, TAX_TYPE_SHORT } from "@/lib/format";
import { usePref } from "@/lib/hooks";
import type { MonteCarlo, Projection, Row } from "@/lib/types";

type Basis = "real" | "nominal";

const n = (r: Row, k: string) => Number(r[k] ?? 0);

export default function PlanPage() {
  const [basis, setBasis] = usePref<Basis>("basis", "real");
  const [proj, setProj] = useState<Projection | null>(null);
  const [mc, setMc] = useState<MonteCarlo | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [settings, setSettings] = usePref("mc-settings", { n_paths: 1000, seed: 20260101, distribution: "normal", degrees_of_freedom: 5 });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [detail, setDetail] = useState<Row | null>(null);

  async function run(s = settings) {
    setBusy(true);
    setError(null);
    try {
      const [p, m] = await Promise.all([api.post<Projection>("/projection"), api.post<MonteCarlo>("/monte-carlo", s)]);
      setProj(p);
      setMc(m);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const k = (r: Row) => (basis === "real" ? r.price_index : 1);
  const dollars = basis === "real" ? "today's dollars" : "future dollars";

  return (
    <>
      <PageHeader
        title="Year by year"
        intro="How your money is expected to move each year: what comes in, what goes out, taxes, and what is left."
        actions={<>
          <Segmented label="Show amounts in" value={basis} onChange={setBasis} options={[{ value: "real", label: "Today's dollars" }, { value: "nominal", label: "Future dollars" }]} />
          <Button variant="secondary" onClick={() => setSettingsOpen(true)}>Simulation settings</Button>
        </>}
      />
      <p className="-mt-3 mb-5 text-sm text-muted">
        <strong>Today&apos;s dollars</strong> removes the effect of rising prices so amounts compare with what things cost now.{" "}
        <strong>Future dollars</strong> are the actual number of dollars in each year.
      </p>
      {busy && !proj && <Loading label="Running your plan..." />}
      <ErrorBox error={error} />

      {proj && mc && (
        <div className="flex flex-col gap-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Chance of success" value={pct(mc.success_probability)} tone={mc.success_probability >= 0.85 ? "good" : mc.success_probability >= 0.7 ? "warn" : "bad"}
              sub={`${mc.n_paths.toLocaleString()} possible futures`}
              help={mc.meta.success_definition} />
            <Stat label="Essentials covered" value={pct(mc.essential_success_probability)} sub="Must-have spending always paid"
              help="The share of futures in which must-have spending is always paid, even if nice-to-have spending has to be cut short." />
            <Stat label="Average-return projection" value={proj.summary.funded ? "Money lasts" : `Short from ${proj.summary.first_shortfall_year}`}
              tone={proj.summary.funded ? "good" : "bad"} sub={`Through ${proj.summary.plan_end_year}`} />
            <Stat label="Middle outcome at the end" value={money(mc.ending_portfolio_real.p50)} sub="today's dollars" />
          </div>

          {(proj.warnings.length > 0 || proj.notes.length > 0) && (
            <Notice tone="info" title="Notes about these results">
              <ul className="list-disc pl-5">{[...proj.notes, ...proj.warnings].map((w) => <li key={w}>{w}</li>)}</ul>
            </Notice>
          )}

          <Card title="Range of possible outcomes" subtitle={`Investments at the end of each year, ${dollars}.`}>
            <FanChart
              years={mc.years}
              ages={proj.rows.map((r) => Object.values(r.ages).find((a) => a !== null) ?? null)}
              p10={basis === "real" ? mc.portfolio_real.p10 : mc.portfolio_nominal.p10}
              p50={basis === "real" ? mc.portfolio_real.p50 : mc.portfolio_nominal.p50}
              p90={basis === "real" ? mc.portfolio_real.p90 : mc.portfolio_nominal.p90}
              projection={proj.rows.map((r) => n(r, "portfolio") / k(r))}
            />
            <AssumptionLine>
              {mc.n_paths.toLocaleString()} simulated futures · seed {mc.meta.seed} · {mc.meta.distribution} returns · inflation {pct(proj.meta.inflation_assumption, 1)}/yr ·
              tax rules {proj.meta.tax_rule_versions.join(", ")} · engine {proj.meta.engine_version} · NumPy {mc.meta.numpy_version} · input {proj.meta.plan_hash.slice(0, 12)}
              {mc.cached ? " · loaded from a saved run with identical inputs" : mc.duration_ms ? ` · ran in ${(mc.duration_ms / 1000).toFixed(1)}s` : ""}
            </AssumptionLine>
          </Card>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card title="Where the money comes from" subtitle={`Each year, ${dollars}, average-return projection.`}>
              <CashFlowChart data={proj.rows.map((r) => ({
                year: r.year,
                pay: n(r, "wages") / k(r),
                ss: n(r, "social_security") / k(r),
                other: (n(r, "other_income") + n(r, "tax_free_income")) / k(r),
                savings: Math.max(n(r, "withdrawals_total") - n(r, "surplus_saved"), 0) / k(r),
                spending: (n(r, "spending_total") + n(r, "tax_total")) / k(r),
              }))} />
            </Card>
            <Card title="Savings by account type" subtitle={`End of each year, ${dollars}, average-return projection.`}>
              <StackedBalances
                data={proj.rows.map((r) => ({
                  year: r.year,
                  cash: n(r, "balance_cash") / k(r), taxable: n(r, "balance_taxable") / k(r), traditional: n(r, "balance_traditional") / k(r),
                  roth: n(r, "balance_roth") / k(r), hsa: n(r, "balance_hsa") / k(r),
                }))}
                keys={["cash", "taxable", "traditional", "roth", "hsa"].filter((t) => proj.rows.some((r) => n(r, `balance_${t}`) > 0))
                  .map((t) => ({ key: t, label: TAX_TYPE_SHORT[t], color: TAX_TYPE_COLOR[t] }))}
              />
            </Card>
          </div>

          <Card title="Year-by-year table" subtitle={`Average-return projection, ${dollars}. Select a year for the full breakdown.`}>
            <Table
              caption="Year by year"
              numericFrom={2}
              head={["Year", "Ages", "Income", "Spending", "Taxes", "From savings", "Investments", ""]}
              rows={proj.rows.map((r) => [
                r.year,
                Object.values(r.ages).filter((a) => a !== null).join(" / "),
                money((n(r, "wages") + n(r, "social_security") + n(r, "other_income") + n(r, "tax_free_income")) / k(r)),
                money(n(r, "spending_total") / k(r)),
                money(n(r, "tax_total") / k(r)),
                money(Math.max(n(r, "withdrawals_total") - n(r, "surplus_saved"), 0) / k(r)),
                <span key="p" className={n(r, "shortfall") > 0 ? "font-semibold text-bad" : ""}>{money(n(r, "portfolio") / k(r))}{n(r, "shortfall") > 0 ? " (short)" : ""}</span>,
                <Button key="d" variant="ghost" className="min-h-8 px-2 text-sm" onClick={() => setDetail(r)}>Details</Button>,
              ])}
            />
          </Card>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card title="Money left at the end" subtitle="Across all simulated futures, today's dollars.">
              <Histogram edges={mc.ending_portfolio_real_histogram.edges} counts={mc.ending_portfolio_real_histogram.counts} />
              <p className="mt-2 text-sm text-muted">
                Poor markets (1 in 10 futures do worse): {money(mc.ending_portfolio_real.p10)}. Middle: {money(mc.ending_portfolio_real.p50)}.
                Strong markets (1 in 10 do better): {money(mc.ending_portfolio_real.p90)}.
              </p>
            </Card>
            <Card title={<>Spending guardrails<Help text="An optional rule: when investments fall a lot, trim nice-to-have spending a little; when they do very well, allow a little more. Must-haves are never cut. Turn it on under Settings." /></>}>
              {mc.guardrails.enabled ? (
                <ul className="space-y-2">
                  <li>In <strong>{pct(mc.guardrails.paths_with_a_cut)}</strong> of futures, nice-to-have spending was trimmed at some point.</li>
                  <li>In <strong>{pct(mc.guardrails.paths_with_a_raise)}</strong> of futures, there was room to spend more.</li>
                  <li>In a bad case (1 in 10), nice-to-have spending fell to <strong>{pct(mc.guardrails.lowest_multiplier_p10)}</strong> of plan at its lowest.</li>
                </ul>
              ) : (
                <p className="text-muted">Guardrails are off. Spending follows your plan exactly in every future. Turning them on can raise the chance of success in exchange for flexibility.</p>
              )}
              {mc.median_failure_age && (
                <p className="mt-3 text-muted">In the futures where money ran short, it typically happened around age {mc.median_failure_age} ({mc.median_failure_year}).</p>
              )}
            </Card>
          </div>
        </div>
      )}

      <Modal open={settingsOpen} onClose={() => setSettingsOpen(false)} title="Simulation settings">
        <div className="flex flex-col gap-4">
          <p className="text-muted">These control the &quot;possible futures&quot;. The same settings always give exactly the same answer.</p>
          <Field label="Number of futures" htmlFor="s-n" hint="More is steadier but slower. 1,000 is plenty for most uses.">
            <Select id="s-n" value={String(settings.n_paths)} onChange={(v) => setSettings({ ...settings, n_paths: Number(v) })}
              options={[500, 1000, 2000, 5000, 10000].map((x) => ({ value: String(x), label: x.toLocaleString() }))} />
          </Field>
          <Field label="Seed" htmlFor="s-seed" help="A number that fixes which random futures are used. Change it to see a different set of futures; keep it to reproduce a result exactly.">
            <NumberInput id="s-seed" value={settings.seed} step={1} min={0} onChange={(v) => setSettings({ ...settings, seed: v ?? 0 })} />
          </Field>
          <Field label="How extreme can years be?" htmlFor="s-dist" help="'Normal' is the standard bell curve. 'Fat tails' and 'Laplace' make very bad (and very good) years more common, which is more cautious.">
            <Select id="s-dist" value={settings.distribution} onChange={(v) => setSettings({ ...settings, distribution: v })} options={[
              { value: "normal", label: "Normal (standard)" },
              { value: "student_t", label: "Fat tails (Student-t): more extreme years" },
              { value: "laplace", label: "Laplace: more extreme years" },
            ]} />
          </Field>
          {settings.distribution === "student_t" && (
            <Field label="Degrees of freedom" htmlFor="s-df" hint="Lower means fatter tails. 4-6 is typical.">
              <NumberInput id="s-df" value={settings.degrees_of_freedom} min={2.1} max={100} onChange={(v) => setSettings({ ...settings, degrees_of_freedom: v ?? 5 })} />
            </Field>
          )}
          <div className="flex gap-2">
            <Button busy={busy} onClick={async () => { await run(settings); setSettingsOpen(false); }}>Run</Button>
            <Button variant="secondary" onClick={() => setSettings({ n_paths: 1000, seed: 20260101, distribution: "normal", degrees_of_freedom: 5 })}>Reset</Button>
          </div>
        </div>
      </Modal>

      <Modal open={detail !== null} onClose={() => setDetail(null)} title={`${detail?.year ?? ""} in detail`} wide>
        {detail && <YearDetail r={detail} basis={basis} />}
      </Modal>
    </>
  );
}

function YearDetail({ r, basis }: { r: Row; basis: Basis }) {
  const k = basis === "real" ? r.price_index : 1;
  const m = (key: string) => money(n(r, key) / k);
  const line = (label: string, key: string, help?: string) => n(r, key) !== 0 ? [<span key="l">{label}{help && <Help text={help} />}</span>, m(key)] : null;
  const group = (rows: (React.ReactNode[] | null)[]) => rows.filter((x): x is React.ReactNode[] => x !== null);
  return (
    <div className="grid gap-6 md:grid-cols-2">
      <div className="flex flex-col gap-4">
        <Table head={["Money in", ""]} rows={group([
          line("Pay", "wages"), line("Social Security", "social_security"), line("Pensions & other income", "other_income"),
          line("Tax-free income", "tax_free_income"), line("Property / business sale", "asset_sale_proceeds"),
          line("Required withdrawals (RMD)", "rmd", "From age 73 or 75 the government requires a minimum withdrawal from pre-tax accounts each year."),
          line("From savings", "withdrawals_cash"), line("From taxable investments", "withdrawals_taxable"),
          line("From pre-tax accounts (beyond RMD)", "withdrawals_traditional"), line("From Roth", "withdrawals_roth"), line("From HSA (health costs)", "hsa_withdrawals"),
        ])} />
        <Table head={["Money out", ""]} rows={group([
          line("Must-have spending", "expenses_essential"), line("Nice-to-have spending", "expenses_discretionary"),
          line("Debt payments", "debt_payments"), line("Medicare premiums", "medicare_premiums"),
          line("Saved into accounts", "contributions"), line("Unspent money saved", "surplus_saved"), line("Shortfall (not covered)", "shortfall"),
        ])} />
      </div>
      <div className="flex flex-col gap-4">
        <Table head={["Taxes", ""]} rows={group([
          line("Federal income tax", "tax_federal_ordinary"), line("Tax on investment gains & dividends", "tax_federal_ltcg"),
          line("Investment income surtax (NIIT)", "tax_niit"), line("State income tax", "tax_state"),
          line("Social Security & Medicare tax on pay", "tax_payroll"), line("Early-withdrawal penalty", "tax_penalty"),
          [<strong key="t">Total</strong>, <strong key="v">{m("tax_total")}</strong>],
        ])} />
        <Table head={["Tax details", ""]} rows={group([
          line("Roth conversion", "roth_conversion", "Money moved from a pre-tax account to a Roth account this year. It is taxed now so it can come out tax-free later."),
          line("Adjusted gross income (AGI)", "agi"), line("Taxable Social Security", "taxable_ss"), line("Deductions", "deduction"),
          line("Taxable income", "taxable_income"),
          [<span key="b">Tax bracket</span>, pct(n(r, "marginal_rate"))],
        ])} />
        <Table head={["End of year", ""]} rows={group([
          line("Savings", "balance_cash"), line("Taxable investments", "balance_taxable"), line("Pre-tax accounts", "balance_traditional"),
          line("Roth", "balance_roth"), line("HSA", "balance_hsa"), line("Home & property", "other_assets"), line("Debts", "liabilities"),
          [<strong key="nw">Net worth</strong>, <strong key="v">{m("net_worth")}</strong>],
        ])} />
      </div>
      <p className="text-xs text-muted md:col-span-2">
        {basis === "real" ? "Today's dollars." : "Future dollars."} Filing status: {r.filing_status === "mfj" ? "married filing jointly" : "single"}. Cash flows happen at the start of the year; investment returns are added afterwards.
      </p>
    </div>
  );
}
