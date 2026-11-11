"use client";

import { useState } from "react";
import { Donut } from "@/components/charts";
import { AccountForm } from "@/components/forms";
import {
  AssumptionLine, Badge, Button, Card, Empty, ErrorBox, Field, Help, Loading, Modal, MoneyInput, Notice, NumberInput,
  PageHeader, PercentInput, Select, Stat, Table, TextInput, Toggle,
} from "@/components/ui";
import { api } from "@/lib/api";
import { CLASS_COLOR, dateText, money, pct, TAX_TYPE_COLOR, TAX_TYPE_LABEL, TAX_TYPE_SHORT } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { AccountRow, MemberRow } from "@/lib/types";

interface NetWorth {
  investments: number;
  investments_by_type: Record<string, number>;
  property: number;
  businesses: number;
  debts: number;
  net_worth: number;
  note: string;
}

interface Analytics {
  total_value: number;
  by_asset_class: { key: string; name: string; value: number; share: number }[];
  by_tax_type: { key: string; value: number; share: number }[];
  positions: { key: string; name: string; value: number; share: number; direct: number; through_funds: number; is_fund: boolean }[];
  concentration: { flags: { level: string; code: string; message: string }[]; hhi: number; top5_share: number };
  look_through: { covered_value: number; covered_share: number; not_covered: { symbol: string; name: string; value: number }[] };
  as_of: string | null;
  data_note: string;
}

export default function Money() {
  const members = useApi<MemberRow[]>("/members");
  const accounts = useApi<AccountRow[]>("/accounts");
  const nw = useApi<NetWorth>("/networth");
  const analytics = useApi<Analytics>("/analytics/portfolio");
  const [editing, setEditing] = useState<AccountRow | "new" | null>(null);
  const [holdingsFor, setHoldingsFor] = useState<AccountRow | null>(null);
  const [importOpen, setImportOpen] = useState(false);

  const reloadAll = () => {
    accounts.reload();
    nw.reload();
    analytics.reload();
  };

  async function remove(a: AccountRow) {
    if (!window.confirm(`Remove "${a.name}"? This cannot be undone.`)) return;
    await api.del(`/accounts/${a.id}`);
    reloadAll();
  }

  return (
    <>
      <PageHeader
        title="My money"
        intro="Everything you own and owe. Enter balances by hand or import a file; no bank connection is needed."
        actions={<>
          <Button onClick={() => setEditing("new")}>+ Add account</Button>
          <Button variant="secondary" onClick={() => setImportOpen(true)}>Import from a file</Button>
        </>}
      />

      {nw.data && (
        <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Net worth" value={money(nw.data.net_worth)} help="Everything you own minus everything you owe." />
          <Stat label="Savings & investments" value={money(nw.data.investments)} />
          <Stat label="Home & property" value={money(nw.data.property + nw.data.businesses)} />
          <Stat label="Debts" value={money(nw.data.debts)} tone={nw.data.debts > 0 ? "warn" : undefined} />
        </div>
      )}

      <Card title="Accounts" className="mb-6">
        {accounts.loading && !accounts.data && <Loading />}
        <ErrorBox error={accounts.error} />
        {accounts.data?.length === 0 && (
          <Empty title="No accounts yet" action={<Button onClick={() => setEditing("new")}>Add your first account</Button>}>
            Start with your biggest ones: a 401(k), an IRA, a brokerage account, your savings.
          </Empty>
        )}
        {accounts.data && accounts.data.length > 0 && (
          <ul className="divide-y divide-line">
            {accounts.data.map((a) => {
              const owner = members.data?.find((m) => m.id === a.member_id)?.name ?? "Joint";
              return (
                <li key={a.id} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <p className="font-semibold">
                      <span className="mr-2 inline-block h-3 w-3 rounded-sm align-middle" style={{ background: TAX_TYPE_COLOR[a.tax_type] }} />
                      {a.name}
                    </p>
                    <p className="text-sm text-muted">
                      {TAX_TYPE_LABEL[a.tax_type]} · {owner}
                      {a.institution ? ` · ${a.institution}` : ""}
                      {a.has_holdings ? ` · ${a.holdings.length} investment${a.holdings.length === 1 ? "" : "s"}` : ""}
                      {" · "}as of {dateText(a.balance_as_of)}
                      {a.source === "csv" && <Badge>imported</Badge>}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="mr-2 text-lg font-semibold tabular-nums">{money(a.value)}</span>
                    {a.tax_type !== "cash" && <Button variant="ghost" onClick={() => setHoldingsFor(a)}>Investments</Button>}
                    <Button variant="ghost" onClick={() => setEditing(a)}>Edit</Button>
                    <Button variant="ghost" onClick={() => remove(a)} aria-label={`Remove ${a.name}`}>Remove</Button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      {analytics.data && analytics.data.total_value > 0 && (
        <div className="mb-6 grid gap-6 lg:grid-cols-2">
          <Card title="How your money is invested" subtitle="Looking inside funds where we know what they hold.">
            <Donut data={analytics.data.by_asset_class.map((c) => ({ name: c.name, value: c.value, color: CLASS_COLOR[c.key] ?? "#a0a6a3" }))} />
            <AssumptionLine>{analytics.data.data_note}</AssumptionLine>
          </Card>
          <Card title="By tax treatment" subtitle="This matters for how much tax you pay when you take money out.">
            <Donut data={analytics.data.by_tax_type.map((c) => ({ name: TAX_TYPE_SHORT[c.key] ?? c.key, value: c.value, color: TAX_TYPE_COLOR[c.key] ?? "#a0a6a3" }))} />
          </Card>
        </div>
      )}

      {analytics.data && analytics.data.positions.length > 0 && (
        <Card
          title={<>Concentration check<Help text="Having a lot of money in one company is risky: if it does badly, it hurts more. Funds already spread money over many companies. We combine what you own directly with what your funds hold." /></>}
          className="mb-6"
        >
          {analytics.data.concentration.flags.length === 0 ? (
            <Notice tone="good">Nothing stands out. No single company makes up more than 10% of your investments.</Notice>
          ) : (
            <div className="flex flex-col gap-2">
              {analytics.data.concentration.flags.map((f) => (
                <Notice key={f.message} tone={f.level === "warning" ? "warn" : "info"}>{f.message}</Notice>
              ))}
            </div>
          )}
          <Table
            className="mt-4"
            caption="Largest positions"
            head={["Holding", "Total", "Owned directly", "Through funds", "Share"]}
            rows={analytics.data.positions.slice(0, 10).map((p) => [
              <span key="n">{p.name}{p.is_fund && <span className="ml-2"><Badge>fund</Badge></span>}</span>,
              money(p.value), money(p.direct), money(p.through_funds), pct(p.share, 1),
            ])}
          />
          <p className="mt-3 text-sm text-muted">
            Look-through coverage: {pct(analytics.data.look_through.covered_share)} of your money.
            {analytics.data.look_through.not_covered.length > 0 && (
              <> No breakdown is stored for: {analytics.data.look_through.not_covered.map((n) => n.symbol || n.name).join(", ")}. You can add one under Investments.</>
            )}
          </p>
        </Card>
      )}

      <PropertyAndDebts onChange={nw.reload} members={members.data ?? []} />

      <Modal open={editing !== null} onClose={() => setEditing(null)} title={editing === "new" ? "Add an account" : "Edit account"} wide>
        {editing !== null && members.data && (
          <AccountForm
            account={editing === "new" ? undefined : editing}
            members={members.data}
            onSaved={() => { setEditing(null); reloadAll(); }}
            onCancel={() => setEditing(null)}
          />
        )}
      </Modal>
      <Modal open={holdingsFor !== null} onClose={() => setHoldingsFor(null)} title={`Investments in ${holdingsFor?.name ?? ""}`} wide>
        {holdingsFor && <HoldingsEditor account={holdingsFor} onChanged={(a) => { setHoldingsFor(a); reloadAll(); }} />}
      </Modal>
      <Modal open={importOpen} onClose={() => setImportOpen(false)} title="Import from a file" wide>
        <CsvImport onDone={reloadAll} />
      </Modal>
    </>
  );
}

function HoldingsEditor({ account, onChanged }: { account: AccountRow; onChanged: (a: AccountRow) => void }) {
  const [d, setD] = useState({ symbol: "", name: "", value: 0 as number | null, cost_basis: null as number | null, asset_class_key: "us_stocks", is_fund: true });
  const [mix, setMix] = useState<{ stocks: number; intl: number; bonds: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const composition = mix ? [
        { kind: "asset_class", key: "us_stocks", weight: mix.stocks },
        { kind: "asset_class", key: "intl_stocks", weight: mix.intl },
        { kind: "asset_class", key: "bonds", weight: mix.bonds },
      ].filter((p) => p.weight > 0) : undefined;
      const a = await api.post<AccountRow>(`/accounts/${account.id}/holdings`, { ...d, value: d.value ?? 0, name: d.name || undefined, composition });
      setD({ symbol: "", name: "", value: 0, cost_basis: null, asset_class_key: "us_stocks", is_fund: true });
      setMix(null);
      onChanged(a);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    await api.del(`/holdings/${id}`);
    const all = await api.get<AccountRow[]>("/accounts");
    onChanged(all.find((x) => x.id === account.id) ?? account);
  }

  return (
    <div className="flex flex-col gap-5">
      <p className="text-muted">
        Optional. Listing the funds or stocks in this account lets us check concentration and the real investment mix.
        When an account has investments listed, its balance is the total of them.
      </p>
      {account.holdings.length > 0 && (
        <Table
          head={["Investment", "Type", "Value", ""]}
          numericFrom={2}
          rows={account.holdings.map((h) => [
            <span key="n"><strong>{h.symbol}</strong> <span className="text-muted">{h.name}</span></span>,
            h.is_fund ? "Fund" : "Single company",
            money(h.value),
            <Button key="r" variant="ghost" onClick={() => remove(h.id)}>Remove</Button>,
          ])}
        />
      )}
      <form onSubmit={add} className="rounded-lg border border-line bg-paper p-4">
        <p className="mb-3 font-semibold">Add an investment</p>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Ticker symbol" htmlFor="h-sym" hint="e.g. VTI, or a short name"><TextInput id="h-sym" value={d.symbol} onChange={(e) => setD({ ...d, symbol: e.target.value })} required /></Field>
          <Field label="Name (optional)" htmlFor="h-name"><TextInput id="h-name" value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} /></Field>
          <Field label="Current value" htmlFor="h-val"><MoneyInput id="h-val" value={d.value} onChange={(v) => setD({ ...d, value: v })} /></Field>
          {account.tax_type === "taxable" && (
            <Field label="What you paid (optional)" htmlFor="h-basis"><MoneyInput id="h-basis" allowEmpty value={d.cost_basis} onChange={(v) => setD({ ...d, cost_basis: v })} /></Field>
          )}
          <Field label="What kind of investment" htmlFor="h-class">
            <Select id="h-class" value={d.asset_class_key} onChange={(v) => setD({ ...d, asset_class_key: v })} options={[
              { value: "us_stocks", label: "US stocks" }, { value: "intl_stocks", label: "International stocks" },
              { value: "bonds", label: "Bonds" }, { value: "cash", label: "Cash / money market" },
              { value: "real_estate", label: "Real estate fund" }, { value: "other", label: "Other / mixed" },
            ]} />
          </Field>
          <div className="flex items-end pb-2">
            <Toggle checked={d.is_fund} onChange={(v) => setD({ ...d, is_fund: v })} label="It is a fund (holds many companies)" />
          </div>
        </div>
        {d.is_fund && (
          <div className="mt-4">
            <Toggle checked={mix !== null} onChange={(v) => setMix(v ? { stocks: 0.6, intl: 0, bonds: 0.4 } : null)}
              label="This fund mixes stocks and bonds (e.g. a target-date or balanced fund)" description="Enter its mix from the fund's fact sheet." />
            {mix && (
              <div className="mt-3 grid gap-3 sm:grid-cols-3">
                <Field label="US stocks" htmlFor="h-m1"><PercentInput id="h-m1" value={mix.stocks} min={0} max={1} onChange={(v) => setMix({ ...mix, stocks: v })} /></Field>
                <Field label="International stocks" htmlFor="h-m2"><PercentInput id="h-m2" value={mix.intl} min={0} max={1} onChange={(v) => setMix({ ...mix, intl: v })} /></Field>
                <Field label="Bonds" htmlFor="h-m3"><PercentInput id="h-m3" value={mix.bonds} min={0} max={1} onChange={(v) => setMix({ ...mix, bonds: v })} /></Field>
              </div>
            )}
          </div>
        )}
        <ErrorBox error={error} />
        <Button type="submit" busy={busy} className="mt-4">Add investment</Button>
      </form>
    </div>
  );
}

function CsvImport({ onDone }: { onDone: () => void }) {
  const templates = useApi<Record<string, string>>("/import/templates");
  const [kind, setKind] = useState("accounts");
  const [content, setContent] = useState("");
  const [result, setResult] = useState<{ imported: number; rows_read: number; errors: { row: number; message: string }[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function run() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const r = await api.post<NonNullable<typeof result>>("/import/csv", { kind, content });
      setResult(r);
      onDone();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-muted">
        Upload a CSV file (most banks and spreadsheet programs can save one). The first row must have the column names shown in the example.
      </p>
      <Field label="What does the file contain?" htmlFor="csv-kind">
        <Select id="csv-kind" value={kind} onChange={setKind} options={[
          { value: "accounts", label: "Accounts and balances" },
          { value: "holdings", label: "Investments in each account" },
          { value: "transactions", label: "Transactions" },
          { value: "expenses", label: "Spending" },
        ]} />
      </Field>
      {templates.data && (
        <div>
          <p className="text-sm font-medium">Example</p>
          <pre className="mt-1 overflow-x-auto rounded-lg border border-line bg-paper p-3 text-xs">{templates.data[kind]}</pre>
        </div>
      )}
      <Field label="Choose file" htmlFor="csv-file">
        <input id="csv-file" type="file" accept=".csv,text/csv" className="text-sm"
          onChange={async (e) => { const f = e.target.files?.[0]; if (f) setContent(await f.text()); }} />
      </Field>
      <Field label="...or paste the contents" htmlFor="csv-text">
        <textarea id="csv-text" rows={5} value={content} onChange={(e) => setContent(e.target.value)}
          className="w-full rounded-lg border border-line p-3 font-mono text-sm" />
      </Field>
      <ErrorBox error={error} />
      {result && (
        <Notice tone={result.errors.length ? "warn" : "good"} title={`Imported ${result.imported} of ${result.rows_read} rows`}>
          {result.errors.length > 0 && (
            <ul className="list-disc pl-5">{result.errors.map((e) => <li key={e.row}>Row {e.row}: {e.message}</li>)}</ul>
          )}
        </Notice>
      )}
      <div><Button onClick={run} busy={busy} disabled={!content.trim()}>Import</Button></div>
    </div>
  );
}

interface Property { id: string; name: string; value: number; cost_basis: number; growth_rate: number; sale_year: number | null; sale_cost_pct: number; primary_residence: boolean; value_as_of: string | null }
interface Debt { id: string; name: string; kind: string; balance: number; interest_rate: number; monthly_payment: number; real_estate_id: string | null }
interface Biz { id: string; name: string; member_id: string | null; value: number; cost_basis: number; growth_rate: number; annual_income: number; sale_year: number | null; sale_cost_pct: number }

function PropertyAndDebts({ onChange, members }: { onChange: () => void; members: MemberRow[] }) {
  const props = useApi<Property[]>("/real-estate");
  const debts = useApi<Debt[]>("/liabilities");
  const biz = useApi<Biz[]>("/businesses");
  const [open, setOpen] = useState<null | { kind: "property"; row?: Property } | { kind: "debt"; row?: Debt } | { kind: "biz"; row?: Biz }>(null);
  const done = () => { setOpen(null); props.reload(); debts.reload(); biz.reload(); onChange(); };
  async function del(path: string, name: string) {
    if (!window.confirm(`Remove "${name}"?`)) return;
    await api.del(path);
    done();
  }
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="Home, property & business" actions={<>
        <Button variant="secondary" onClick={() => setOpen({ kind: "property" })}>+ Property</Button>
        <Button variant="secondary" onClick={() => setOpen({ kind: "biz" })}>+ Business</Button>
      </>}>
        {props.data?.length === 0 && biz.data?.length === 0 && <p className="text-muted">Nothing added. Add your home if you own it.</p>}
        <ul className="divide-y divide-line">
          {props.data?.map((p) => (
            <li key={p.id} className="flex items-center justify-between gap-2 py-2">
              <span><strong>{p.name}</strong><span className="block text-sm text-muted">{p.sale_year ? `Sell in ${p.sale_year}` : "Keep"} · grows {pct(p.growth_rate, 1)} a year</span></span>
              <span className="flex items-center gap-1"><span className="tabular-nums">{money(p.value)}</span>
                <Button variant="ghost" onClick={() => setOpen({ kind: "property", row: p })}>Edit</Button>
                <Button variant="ghost" onClick={() => del(`/real-estate/${p.id}`, p.name)}>Remove</Button></span>
            </li>
          ))}
          {biz.data?.map((b) => (
            <li key={b.id} className="flex items-center justify-between gap-2 py-2">
              <span><strong>{b.name}</strong><span className="block text-sm text-muted">Business{b.annual_income ? ` · pays ${money(b.annual_income)} a year` : ""}</span></span>
              <span className="flex items-center gap-1"><span className="tabular-nums">{money(b.value)}</span>
                <Button variant="ghost" onClick={() => setOpen({ kind: "biz", row: b })}>Edit</Button>
                <Button variant="ghost" onClick={() => del(`/businesses/${b.id}`, b.name)}>Remove</Button></span>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="What you owe" actions={<Button variant="secondary" onClick={() => setOpen({ kind: "debt" })}>+ Debt</Button>}>
        {debts.data?.length === 0 && <p className="text-muted">No debts. Add a mortgage, car loan or other loan if you have one.</p>}
        <ul className="divide-y divide-line">
          {debts.data?.map((d) => (
            <li key={d.id} className="flex items-center justify-between gap-2 py-2">
              <span><strong>{d.name}</strong><span className="block text-sm text-muted">{money(d.monthly_payment)}/month at {pct(d.interest_rate, 2)}</span></span>
              <span className="flex items-center gap-1"><span className="tabular-nums">{money(d.balance)}</span>
                <Button variant="ghost" onClick={() => setOpen({ kind: "debt", row: d })}>Edit</Button>
                <Button variant="ghost" onClick={() => del(`/liabilities/${d.id}`, d.name)}>Remove</Button></span>
            </li>
          ))}
        </ul>
        <AssumptionLine>Debt payments are counted as spending until each debt is paid off.</AssumptionLine>
      </Card>

      <Modal open={open !== null} onClose={() => setOpen(null)} title={open?.kind === "debt" ? "Debt" : open?.kind === "biz" ? "Business" : "Property"} wide>
        {open?.kind === "property" && <PropertyForm row={open.row} onSaved={done} />}
        {open?.kind === "debt" && <DebtForm row={open.row} properties={props.data ?? []} onSaved={done} />}
        {open?.kind === "biz" && <BizForm row={open.row} members={members} onSaved={done} />}
      </Modal>
    </div>
  );
}

function useSubmit(fn: () => Promise<unknown>, onSaved: () => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  return { busy, error, submit: async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setError(null);
    try { await fn(); onSaved(); } catch (err) { setError(err); } finally { setBusy(false); }
  } };
}

function PropertyForm({ row, onSaved }: { row?: Property; onSaved: () => void }) {
  const [d, setD] = useState({ name: row?.name ?? "Home", value: row?.value ?? 0, cost_basis: row?.cost_basis ?? 0, growth_rate: row?.growth_rate ?? 0.03,
    sale_year: row?.sale_year ?? null, sale_cost_pct: row?.sale_cost_pct ?? 0.06, primary_residence: row?.primary_residence ?? true });
  const s = useSubmit(() => (row ? api.put(`/real-estate/${row.id}`, d) : api.post("/real-estate", d)), onSaved);
  return (
    <form onSubmit={s.submit} className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Name" htmlFor="r-n"><TextInput id="r-n" value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} required /></Field>
        <Field label="What it is worth today" htmlFor="r-v"><MoneyInput id="r-v" value={d.value} onChange={(v) => setD({ ...d, value: v ?? 0 })} /></Field>
        <Field label="What you paid (plus improvements)" htmlFor="r-b" help="Used to work out tax if you sell. Married couples can usually exclude $500,000 of profit on a main home ($250,000 if single).">
          <MoneyInput id="r-b" value={d.cost_basis} onChange={(v) => setD({ ...d, cost_basis: v ?? 0 })} /></Field>
        <Field label="Value grows per year" htmlFor="r-g"><PercentInput id="r-g" value={d.growth_rate} onChange={(v) => setD({ ...d, growth_rate: v })} /></Field>
        <Field label="Year you plan to sell (optional)" htmlFor="r-s" hint="The money from the sale is added to savings that year, after paying off any linked mortgage.">
          <NumberInput id="r-s" value={d.sale_year} allowEmpty step={1} onChange={(v) => setD({ ...d, sale_year: v })} /></Field>
        <Field label="Selling costs" htmlFor="r-c"><PercentInput id="r-c" value={d.sale_cost_pct} min={0} max={0.5} onChange={(v) => setD({ ...d, sale_cost_pct: v })} /></Field>
        <div className="sm:col-span-2"><Toggle checked={d.primary_residence} onChange={(v) => setD({ ...d, primary_residence: v })} label="This is our main home" /></div>
      </div>
      <ErrorBox error={s.error} />
      <div><Button type="submit" busy={s.busy}>Save</Button></div>
    </form>
  );
}

function DebtForm({ row, properties, onSaved }: { row?: Debt; properties: Property[]; onSaved: () => void }) {
  const [d, setD] = useState({ name: row?.name ?? "Mortgage", kind: row?.kind ?? "mortgage", balance: row?.balance ?? 0, interest_rate: row?.interest_rate ?? 0.05,
    monthly_payment: row?.monthly_payment ?? 0, real_estate_id: (row?.real_estate_id ?? properties[0]?.id ?? null) as string | null });
  const s = useSubmit(() => (row ? api.put(`/liabilities/${row.id}`, d) : api.post("/liabilities", d)), onSaved);
  return (
    <form onSubmit={s.submit} className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Name" htmlFor="d-n"><TextInput id="d-n" value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} required /></Field>
        <Field label="Kind" htmlFor="d-k"><Select id="d-k" value={d.kind} onChange={(v) => setD({ ...d, kind: v })} options={[
          { value: "mortgage", label: "Mortgage" }, { value: "car_loan", label: "Car loan" }, { value: "student_loan", label: "Student loan" },
          { value: "credit_card", label: "Credit card" }, { value: "other", label: "Other" }]} /></Field>
        <Field label="Amount still owed" htmlFor="d-b"><MoneyInput id="d-b" value={d.balance} onChange={(v) => setD({ ...d, balance: v ?? 0 })} /></Field>
        <Field label="Interest rate" htmlFor="d-r"><PercentInput id="d-r" value={d.interest_rate} min={0} max={0.5} onChange={(v) => setD({ ...d, interest_rate: v })} /></Field>
        <Field label="Monthly payment" htmlFor="d-p" hint="Principal and interest only (not property tax or insurance)."><MoneyInput id="d-p" value={d.monthly_payment} onChange={(v) => setD({ ...d, monthly_payment: v ?? 0 })} /></Field>
        {d.kind === "mortgage" && properties.length > 0 && (
          <Field label="Which property" htmlFor="d-prop"><Select id="d-prop" value={d.real_estate_id ?? ""} onChange={(v) => setD({ ...d, real_estate_id: v || null })}
            options={[{ value: "", label: "None" }, ...properties.map((p) => ({ value: p.id, label: p.name }))]} /></Field>
        )}
      </div>
      <ErrorBox error={s.error} />
      <div><Button type="submit" busy={s.busy}>Save</Button></div>
    </form>
  );
}

function BizForm({ row, members, onSaved }: { row?: Biz; members: MemberRow[]; onSaved: () => void }) {
  const [d, setD] = useState({ name: row?.name ?? "", member_id: row?.member_id ?? members[0]?.id ?? null, value: row?.value ?? 0, cost_basis: row?.cost_basis ?? 0,
    growth_rate: row?.growth_rate ?? 0.03, annual_income: row?.annual_income ?? 0, sale_year: row?.sale_year ?? null, sale_cost_pct: row?.sale_cost_pct ?? 0.05 });
  const s = useSubmit(() => (row ? api.put(`/businesses/${row.id}`, d) : api.post("/businesses", d)), onSaved);
  return (
    <form onSubmit={s.submit} className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Name" htmlFor="b-n"><TextInput id="b-n" value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} required /></Field>
        <Field label="Estimated value of your share" htmlFor="b-v"><MoneyInput id="b-v" value={d.value} onChange={(v) => setD({ ...d, value: v ?? 0 })} /></Field>
        <Field label="Income it pays you each year" htmlFor="b-i"><MoneyInput id="b-i" value={d.annual_income} onChange={(v) => setD({ ...d, annual_income: v ?? 0 })} /></Field>
        <Field label="What you put in (cost basis)" htmlFor="b-b"><MoneyInput id="b-b" value={d.cost_basis} onChange={(v) => setD({ ...d, cost_basis: v ?? 0 })} /></Field>
        <Field label="Value grows per year" htmlFor="b-g"><PercentInput id="b-g" value={d.growth_rate} onChange={(v) => setD({ ...d, growth_rate: v })} /></Field>
        <Field label="Year you plan to sell (optional)" htmlFor="b-s"><NumberInput id="b-s" value={d.sale_year} allowEmpty step={1} onChange={(v) => setD({ ...d, sale_year: v })} /></Field>
      </div>
      <ErrorBox error={s.error} />
      <div><Button type="submit" busy={s.busy}>Save</Button></div>
    </form>
  );
}
