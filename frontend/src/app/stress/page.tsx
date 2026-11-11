"use client";

import { useState } from "react";
import { SimpleLines } from "@/components/charts";
import { Badge, Button, Card, cx, ErrorBox, Field, Loading, Notice, NumberInput, PageHeader, PercentInput, Select, Table } from "@/components/ui";
import { api } from "@/lib/api";
import { money, pct } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Summary } from "@/lib/types";

interface Historical { key: string; name: string; plain: string; years: { year: number; equity: number; bond: number; cash: number; inflation: number }[]; data_note: string; as_of: string }
interface SlimRow { year: number; portfolio: number; net_worth: number; spending_total: number; shortfall: number; tax_total: number; portfolio_return: number }
interface StressResult {
  kind: string;
  name: string;
  plain?: string;
  label: string;
  start_year: number;
  applied: Record<string, unknown>[];
  baseline_summary: Summary;
  stressed_summary: Summary;
  years: number[];
  price_index: number[];
  baseline_price_index: number[];
  baseline_rows: SlimRow[];
  stressed_rows: SlimRow[];
  data_note?: string;
  warnings: string[];
}

export default function Stress() {
  const hist = useApi<Historical[]>("/stress/historical");
  const [result, setResult] = useState<StressResult | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [startYear, setStartYear] = useState<number | null>(null);
  const [custom, setCustom] = useState({ equity_return: -0.3, duration_years: 1, inflation: null as number | null, inflation_years: 3, return_reduction: 0, extra_years_of_life: 0 });

  async function run(label: string, body: Record<string, unknown>) {
    setBusy(label);
    setError(null);
    try {
      setResult(await api.post<StressResult>("/stress/run", { ...body, start_year: startYear ?? undefined }));
      setTimeout(() => {
        document.getElementById("stress-result")?.scrollIntoView({ behavior: "smooth" });
      }, 50);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <PageHeader title="Bad-market tests" intro="What would happen to your plan in a rough stretch? Pick a test below. These are checks, not predictions." />

      <Card className="mb-6" title="When should the bad stretch start?">
        <div className="flex flex-wrap items-end gap-4">
          <Field label="Starting year" htmlFor="sy" hint="Leave blank to start in the first year everyone is retired, which is usually the riskiest moment.">
            <NumberInput id="sy" step={1} allowEmpty value={startYear} onChange={setStartYear} placeholder="First retirement year" />
          </Field>
        </div>
      </Card>

      <h2 className="mb-3 text-lg font-semibold">Replay a real past crisis</h2>
      {hist.loading && <Loading />}
      <div className="mb-2 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {hist.data?.map((h) => (
          <Card key={h.key} className="flex flex-col">
            <p className="font-semibold">{h.name}</p>
            <p className="mt-1 flex-1 text-sm text-muted">{h.plain}</p>
            <p className="mt-2 text-xs text-muted">Stocks: {h.years.map((y) => `${y.equity > 0 ? "+" : ""}${y.equity}%`).join(", ")}</p>
            <Button variant="secondary" className="mt-3" busy={busy === h.key} onClick={() => run(h.key, { kind: "historical", key: h.key })}>Run this test</Button>
          </Card>
        ))}
      </div>
      {hist.data?.[0] && <p className="mb-6 text-xs text-muted">{hist.data[0].data_note}</p>}

      <div className="mb-6 grid gap-6 lg:grid-cols-2">
        <Card title="Bad years right after retiring" subtitle="Same average return over the plan, just in a worse order.">
          <p className="text-muted">Five poor years come first, then five good years. This shows why the first years of retirement matter most (called &quot;sequence risk&quot;).</p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="secondary" busy={busy === "bad"} onClick={() => run("bad", { kind: "sequence", order: "bad_first", years: 5 })}>Bad years first</Button>
            <Button variant="secondary" busy={busy === "good"} onClick={() => run("good", { kind: "sequence", order: "good_first", years: 5 })}>Good years first</Button>
          </div>
        </Card>
        <Card title="Make your own test">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Stocks change by" htmlFor="c-eq"><PercentInput id="c-eq" value={custom.equity_return} min={-0.9} max={0.5} onChange={(v) => setCustom({ ...custom, equity_return: v })} /></Field>
            <Field label="For how many years" htmlFor="c-dur"><NumberInput id="c-dur" step={1} min={1} max={10} value={custom.duration_years} onChange={(v) => setCustom({ ...custom, duration_years: v ?? 1 })} /></Field>
            <Field label="Inflation during the test" htmlFor="c-inf" hint="Leave blank to keep your normal assumption">
              <Select id="c-inf" value={String(custom.inflation ?? "")} onChange={(v) => setCustom({ ...custom, inflation: v === "" ? null : Number(v) })}
                options={[{ value: "", label: "Normal" }, ...[0.05, 0.07, 0.09, 0.12].map((x) => ({ value: String(x), label: `${x * 100}% a year` }))]} />
            </Field>
            {custom.inflation !== null && (
              <Field label="High inflation lasts (years)" htmlFor="c-iy"><NumberInput id="c-iy" step={1} min={1} max={15} value={custom.inflation_years} onChange={(v) => setCustom({ ...custom, inflation_years: v ?? 3 })} /></Field>
            )}
            <Field label="Lower returns for the whole plan" htmlFor="c-rr">
              <Select id="c-rr" value={String(custom.return_reduction)} onChange={(v) => setCustom({ ...custom, return_reduction: Number(v) })}
                options={[0, 0.01, 0.02, 0.03].map((x) => ({ value: String(x), label: x ? `${x * 100} point${x === 0.01 ? "" : "s"} lower every year` : "No" }))} />
            </Field>
            <Field label="Living longer" htmlFor="c-life">
              <Select id="c-life" value={String(custom.extra_years_of_life)} onChange={(v) => setCustom({ ...custom, extra_years_of_life: Number(v) })}
                options={[0, 3, 5, 8].map((x) => ({ value: String(x), label: x ? `${x} more years` : "No" }))} />
            </Field>
          </div>
          <Button className="mt-4" busy={busy === "custom"} onClick={() => run("custom", {
            kind: "custom",
            custom: { name: "Your own test", equity_return: custom.equity_return, duration_years: custom.duration_years, inflation: custom.inflation,
              inflation_years: custom.inflation !== null ? custom.inflation_years : null, return_reduction: custom.return_reduction, extra_years_of_life: custom.extra_years_of_life },
          })}>Run my test</Button>
        </Card>
      </div>

      <ErrorBox error={error} />
      {result && <StressView r={result} />}
    </>
  );
}

function StressView({ r }: { r: StressResult }) {
  const b = r.baseline_summary;
  const s = r.stressed_summary;
  const hurt = !s.funded && b.funded;
  return (
    <Card title={`Result: ${r.name}`} className="scroll-mt-4">
      <div id="stress-result" />
      <Notice tone={r.kind === "historical" ? "info" : "warn"} className="mb-4">
        <strong>{r.label}</strong> {r.plain}
      </Notice>
      <div className={cx("mb-4 rounded-lg p-4 text-lg", s.funded ? "bg-good-soft" : "bg-bad-soft")}>
        {s.funded ? (
          <>Your money <strong>still lasts</strong> through {s.plan_end_year}, with about <strong>{money(s.ending_portfolio_real)}</strong> left (today&apos;s dollars) instead of {money(b.ending_portfolio_real)}.</>
        ) : (
          <>Your money would <strong>run short in {s.first_shortfall_year}</strong> (around age {s.first_shortfall_age}){hurt ? ", while the normal plan lasts" : ""}. Unpaid spending would total about {money(s.total_shortfall_real)} in today&apos;s dollars.</>
        )}
      </div>
      <SimpleLines
        data={r.years.map((y, i) => ({
          year: y,
          normal: r.baseline_rows[i] ? r.baseline_rows[i].portfolio / r.baseline_price_index[i] : (null as unknown as number),
          stressed: r.stressed_rows[i].portfolio / r.price_index[i],
        }))}
        lines={[{ key: "normal", label: "Normal plan", color: "#55635e", dashed: true }, { key: "stressed", label: "With this test", color: "#b3372c" }]}
      />
      <p className="text-sm text-muted">Investments at the end of each year, today&apos;s dollars.</p>
      <Table
        className="mt-4"
        caption="What was applied"
        numericFrom={1}
        head={["Plan year", "Stocks", "Bonds", "Cash", "Inflation", "Note"]}
        rows={r.applied.map((a) => [
          String(a.plan_year),
          a.equity !== undefined ? pct(Number(a.equity), 1) : "-",
          a.bond !== undefined ? pct(Number(a.bond), 1) : "-",
          a.cash !== undefined ? pct(Number(a.cash), 1) : "-",
          a.inflation !== undefined ? pct(Number(a.inflation), 1) : "-",
          a.historical_year ? <Badge key="h">as in {String(a.historical_year)}</Badge> : a.shift ? String(a.shift) : "",
        ])}
      />
      {r.data_note && <p className="mt-2 text-xs text-muted">{r.data_note}</p>}
    </Card>
  );
}
