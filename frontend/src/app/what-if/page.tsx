"use client";

import { useState } from "react";
import { SimpleLines } from "@/components/charts";
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, MoneyInput, Notice, NumberInput, PageHeader, Select, Table, TextInput } from "@/components/ui";
import { api } from "@/lib/api";
import { money, pct, signedPoints } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { MemberRow, Summary } from "@/lib/types";

interface Column {
  scenario_id: string | null;
  name: string;
  is_baseline: boolean;
  summary: Summary;
  success_probability: number;
  ending_portfolio_real: Record<string, number>;
  years: number[];
  portfolio_real: number[];
  spending_real: number[];
  input_hash: string;
}

interface Overrides {
  retirement_age: Record<string, number>;
  life_expectancy: Record<string, number>;
  ss_claim_age: Record<string, number>;
  expense_scale: number;
  discretionary_scale: number;
  one_time_expenses: { name: string; amount: number; year: number }[];
  extra_incomes: { name: string; amount: number; start_year: number | null; end_year: number | null }[];
  return_shift: number;
  assumptions: Record<string, unknown>;
}

interface Scenario { id: string; name: string; description: string | null; overrides: Overrides; created_at: string }

const EMPTY: Overrides = {
  retirement_age: {}, life_expectancy: {}, ss_claim_age: {}, expense_scale: 1, discretionary_scale: 1,
  one_time_expenses: [], extra_incomes: [], return_shift: 0, assumptions: {},
};
const COLORS = ["#1b6b58", "#c98f1f", "#3a7ca5", "#8f5fa0", "#b3372c", "#55635e", "#8aa39b"];

function describe(o: Overrides, members: MemberRow[]): string[] {
  const out: string[] = [];
  const name = (id: string) => members.find((m) => m.id === id)?.name ?? "Someone";
  for (const [id, a] of Object.entries(o.retirement_age)) out.push(`${name(id)} retires at ${a}`);
  for (const [id, a] of Object.entries(o.ss_claim_age)) out.push(`${name(id)} starts Social Security at ${a}`);
  for (const [id, a] of Object.entries(o.life_expectancy)) out.push(`${name(id)} plans to age ${a}`);
  if (o.expense_scale !== 1) out.push(`All spending ${o.expense_scale > 1 ? "+" : ""}${Math.round((o.expense_scale - 1) * 100)}%`);
  if (o.discretionary_scale !== 1) out.push(`Nice-to-have spending ${o.discretionary_scale > 1 ? "+" : ""}${Math.round((o.discretionary_scale - 1) * 100)}%`);
  for (const x of o.one_time_expenses) out.push(`${x.name}: ${money(x.amount)} in ${x.year}`);
  for (const x of o.extra_incomes) out.push(`${x.name}: ${money(x.amount)}/yr`);
  if (o.return_shift) out.push(`Investment returns ${o.return_shift > 0 ? "+" : ""}${(o.return_shift * 100).toFixed(1)} points a year`);
  return out;
}

export default function WhatIf() {
  const members = useApi<MemberRow[]>("/members");
  const scenarios = useApi<{ scenarios: Scenario[] }>("/scenarios");
  const [draft, setDraft] = useState<Overrides>(EMPTY);
  const [preview, setPreview] = useState<{ columns: Column[]; note: string; warnings: string[] } | null>(null);
  const [compare, setCompare] = useState<{ columns: Column[]; note: string } | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const year = new Date().getFullYear();

  const ms = members.data ?? [];
  const changes = describe(draft, ms);

  async function act(label: string, fn: () => Promise<void>) {
    setBusy(label);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  }

  const test = () => act("test", async () => setPreview(await api.post("/scenarios/preview", { overrides: draft, n_paths: 1000 })));
  const save = () => act("save", async () => {
    await api.post("/scenarios", { name: name.trim() || changes.join(", ").slice(0, 110) || "What-if", overrides: draft });
    setName("");
    scenarios.reload();
  });
  const runCompare = () => act("compare", async () => setCompare(await api.post("/scenarios/compare", { scenario_ids: picked, n_paths: 1000 })));
  const remove = (s: Scenario) => act("remove", async () => {
    if (!window.confirm(`Delete "${s.name}"?`)) return;
    await api.del(`/scenarios/${s.id}`);
    setPicked((p) => p.filter((x) => x !== s.id));
    scenarios.reload();
  });

  const setPerson = (field: "retirement_age" | "ss_claim_age" | "life_expectancy", id: string, value: number | null, current: number) => {
    const next = { ...draft[field] };
    if (value === null || value === current) delete next[id];
    else next[id] = value;
    setDraft({ ...draft, [field]: next });
  };

  if (members.loading && !members.data) return <Loading />;

  return (
    <>
      <PageHeader title="What if...?" intro="Try changes and see their effect side by side. Your saved plan is never changed here." />

      <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
        <Card title="Try a change" subtitle="Change one or more things, then press Test.">
          <div className="flex flex-col gap-5">
            {ms.map((m) => (
              <div key={m.id} className="rounded-lg border border-line p-4">
                <p className="mb-3 font-semibold">{m.name} (age {m.age})</p>
                <div className="grid gap-3 sm:grid-cols-3">
                  <Field label="Retire at" htmlFor={`r-${m.id}`}>
                    <NumberInput id={`r-${m.id}`} step={1} min={Math.max(m.age, 40)} max={85} value={draft.retirement_age[m.id] ?? m.retirement_age}
                      onChange={(v) => setPerson("retirement_age", m.id, v, m.retirement_age)} />
                  </Field>
                  <Field label="Social Security at" htmlFor={`s-${m.id}`}>
                    <Select id={`s-${m.id}`} value={String(draft.ss_claim_age[m.id] ?? m.ss_claim_age)} onChange={(v) => setPerson("ss_claim_age", m.id, Number(v), m.ss_claim_age)}
                      options={[62, 63, 64, 65, 66, 67, 68, 69, 70].map((a) => ({ value: String(a), label: String(a) }))} />
                  </Field>
                  <Field label="Plan to age" htmlFor={`l-${m.id}`}>
                    <NumberInput id={`l-${m.id}`} step={1} min={m.age + 1} max={110} value={draft.life_expectancy[m.id] ?? m.life_expectancy}
                      onChange={(v) => setPerson("life_expectancy", m.id, v, m.life_expectancy)} />
                  </Field>
                </div>
              </div>
            ))}
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="All spending" htmlFor="sp-all" hint="Change by a percent">
                <Select id="sp-all" value={String(Math.round((draft.expense_scale - 1) * 100))} onChange={(v) => setDraft({ ...draft, expense_scale: 1 + Number(v) / 100 })}
                  options={[-30, -20, -15, -10, -5, 0, 5, 10, 15, 20, 30].map((x) => ({ value: String(x), label: x === 0 ? "No change" : `${x > 0 ? "+" : ""}${x}%` }))} />
              </Field>
              <Field label="Nice-to-have spending only" htmlFor="sp-opt">
                <Select id="sp-opt" value={String(Math.round((draft.discretionary_scale - 1) * 100))} onChange={(v) => setDraft({ ...draft, discretionary_scale: 1 + Number(v) / 100 })}
                  options={[-100, -50, -25, 0, 25, 50, 100].map((x) => ({ value: String(x), label: x === 0 ? "No change" : `${x > 0 ? "+" : ""}${x}%` }))} />
              </Field>
              <Field label="Investment returns" htmlFor="ret" hint="Every year, every investment">
                <Select id="ret" value={String(draft.return_shift)} onChange={(v) => setDraft({ ...draft, return_shift: Number(v) })}
                  options={[-0.03, -0.02, -0.01, 0, 0.01].map((x) => ({ value: String(x), label: x === 0 ? "As assumed" : `${x > 0 ? "+" : ""}${(x * 100).toFixed(0)} point${Math.abs(x) === 0.01 ? "" : "s"} a year` }))} />
              </Field>
            </div>
            <OneTimeAdder year={year} onAdd={(x) => setDraft({ ...draft, one_time_expenses: [...draft.one_time_expenses, x] })} />
            {changes.length > 0 && (
              <div>
                <p className="mb-1 text-sm font-medium">Your changes</p>
                <ul className="flex flex-wrap gap-2">{changes.map((c) => <li key={c}><Badge tone="brand">{c}</Badge></li>)}</ul>
              </div>
            )}
            <ErrorBox error={error} />
            <div className="flex flex-wrap gap-2">
              <Button onClick={test} busy={busy === "test"} disabled={changes.length === 0}>Test</Button>
              <Button variant="secondary" onClick={() => { setDraft(EMPTY); setPreview(null); }}>Start over</Button>
            </div>
          </div>
        </Card>

        <Card title="Result" subtitle="Compared with your current plan, using the same 1,000 futures.">
          {!preview && <p className="text-muted">Make a change on the left and press Test.</p>}
          {busy === "test" && <Loading label="Testing..." />}
          {preview && busy !== "test" && (
            <>
              <ComparisonTable columns={preview.columns} />
              <div className="mt-4">
                <SimpleLines
                  data={preview.columns[0].years.map((y, i) => ({ year: y, a: preview.columns[0].portfolio_real[i], b: preview.columns[1].portfolio_real[i] }))}
                  lines={[{ key: "a", label: "Current plan", color: "#55635e", dashed: true }, { key: "b", label: "With your changes", color: "#1b6b58" }]}
                />
                <p className="text-sm text-muted">Investments each year with average returns, today&apos;s dollars.</p>
              </div>
              {preview.warnings.length > 0 && <Notice tone="info" className="mt-3">{preview.warnings.join(" ")}</Notice>}
              <p className="mt-3 text-sm text-muted">{preview.note}</p>
              <div className="mt-4 flex flex-wrap items-end gap-2 border-t border-line pt-4">
                <Field label="Save this what-if as" htmlFor="sc-name">
                  <TextInput id="sc-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Work two more years" />
                </Field>
                <Button variant="secondary" onClick={save} busy={busy === "save"}>Save</Button>
              </div>
            </>
          )}
        </Card>
      </div>

      <Card title="Saved what-ifs" subtitle="Pick up to 6 to compare with your current plan." className="mt-6">
        {scenarios.data?.scenarios.length === 0 && <Empty title="Nothing saved yet">Test a change above and save it to compare later.</Empty>}
        <ul className="divide-y divide-line">
          {scenarios.data?.scenarios.map((s) => (
            <li key={s.id} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
              <label className="flex items-start gap-3">
                <input type="checkbox" className="mt-1.5 h-5 w-5 accent-[#1b6b58]" checked={picked.includes(s.id)}
                  onChange={(e) => setPicked((p) => (e.target.checked ? [...p, s.id].slice(0, 6) : p.filter((x) => x !== s.id)))} />
                <span>
                  <span className="font-semibold">{s.name}</span>
                  <span className="block text-sm text-muted">{describe(s.overrides, ms).join(" · ") || "No changes"}</span>
                </span>
              </label>
              <Button variant="ghost" onClick={() => remove(s)}>Delete</Button>
            </li>
          ))}
        </ul>
        {!!scenarios.data?.scenarios.length && (
          <Button className="mt-4" onClick={runCompare} busy={busy === "compare"} disabled={picked.length === 0}>Compare side by side</Button>
        )}
        {compare && (
          <div className="mt-6">
            <ComparisonTable columns={compare.columns} />
            <div className="mt-4">
              <SimpleLines
                data={compare.columns[0].years.map((y, i) => Object.fromEntries([["year", y], ...compare.columns.map((c, ci) => [`c${ci}`, c.portfolio_real[i] ?? null])]))}
                lines={compare.columns.map((c, ci) => ({ key: `c${ci}`, label: c.name, color: COLORS[ci % COLORS.length], dashed: c.is_baseline }))}
              />
            </div>
            <p className="mt-2 text-sm text-muted">{compare.note}</p>
          </div>
        )}
      </Card>
    </>
  );
}

function OneTimeAdder({ year, onAdd }: { year: number; onAdd: (x: { name: string; amount: number; year: number }) => void }) {
  const [amount, setAmount] = useState<number | null>(null);
  const [y, setY] = useState<number | null>(year + 1);
  const [nm, setNm] = useState("");
  return (
    <div className="rounded-lg border border-line p-4">
      <p className="mb-3 font-semibold">Add a one-time cost</p>
      <div className="grid gap-3 sm:grid-cols-[2fr_1fr_1fr_auto] sm:items-end">
        <Field label="What" htmlFor="ot-n"><TextInput id="ot-n" value={nm} onChange={(e) => setNm(e.target.value)} placeholder="e.g. New car" /></Field>
        <Field label="Cost" htmlFor="ot-a"><MoneyInput id="ot-a" allowEmpty value={amount} onChange={setAmount} /></Field>
        <Field label="Year" htmlFor="ot-y"><NumberInput id="ot-y" step={1} value={y} min={year} max={year + 60} onChange={setY} /></Field>
        <Button variant="secondary" disabled={!amount || !y} onClick={() => { onAdd({ name: nm || "One-time cost", amount: amount!, year: y! }); setAmount(null); setNm(""); }}>Add</Button>
      </div>
    </div>
  );
}

function ComparisonTable({ columns }: { columns: Column[] }) {
  const base = columns[0];
  return (
    <>
    <Table
      numericFrom={1}
      head={["", ...columns.map((c) => c.name)]}
      rows={[
        ["Chance of success", ...columns.map((c, i) => (
          <span key={i}><strong>{pct(c.success_probability)}</strong>{i > 0 && <span className="ml-2"><Badge tone={c.success_probability - base.success_probability > 0.005 ? "good" : c.success_probability - base.success_probability < -0.005 ? "bad" : "neutral"}>{signedPoints(c.success_probability - base.success_probability)}</Badge></span>}</span>
        ))],
        ["Money lasts (average returns)", ...columns.map((c) => (c.summary.funded ? "Yes" : `Short from ${c.summary.first_shortfall_year}`))],
        ["Left at end, average returns*", ...columns.map((c) => money(c.summary.ending_portfolio_real))],
        ["Left at end, poor markets*", ...columns.map((c) => money(c.ending_portfolio_real.p10))],
        ["Lifetime taxes*", ...columns.map((c) => money(c.summary.lifetime_taxes_real))],
        ["Lifetime spending*", ...columns.map((c) => money(c.summary.lifetime_spending_real))],
      ]}
    />
    <p className="mt-1 text-xs text-muted">* In today&apos;s dollars. &quot;Poor markets&quot; means 1 in 10 simulated futures did worse.</p>
    </>
  );
}
