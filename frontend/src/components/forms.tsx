"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { TAX_TYPE_HELP, TAX_TYPE_LABEL } from "@/lib/format";
import type { AccountRow, MemberRow } from "@/lib/types";
import { Button, ErrorBox, Field, MoneyInput, NumberInput, PercentInput, Select, TextInput, Toggle } from "./ui";

const THIS_YEAR = new Date().getFullYear();

function useSave<T>(save: () => Promise<T>, onSaved: (r: T) => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  return {
    busy,
    error,
    submit: async (e?: React.FormEvent) => {
      e?.preventDefault();
      setBusy(true);
      setError(null);
      try {
        onSaved(await save());
      } catch (err) {
        setError(err);
      } finally {
        setBusy(false);
      }
    },
  };
}

function Actions({ busy, onCancel, label = "Save" }: { busy: boolean; onCancel?: () => void; label?: string }) {
  return (
    <div className="flex flex-wrap gap-2 pt-2">
      <Button type="submit" busy={busy}>{label}</Button>
      {onCancel && <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>}
    </div>
  );
}

// ----------------------------------------------------------------------------- people

export type MemberDraft = Omit<MemberRow, "id" | "age">;

export function blankMember(kind: "self" | "spouse"): MemberDraft {
  return {
    name: "",
    relationship_kind: kind,
    birth_year: THIS_YEAR - 60,
    retirement_age: 65,
    life_expectancy: 92,
    ss_monthly_benefit: 0,
    ss_basis: "at_fra",
    ss_claim_age: 67,
  };
}

export function MemberFields({ value, onChange }: { value: MemberDraft; onChange: (v: MemberDraft) => void }) {
  const set = <K extends keyof MemberDraft>(k: K, v: MemberDraft[K]) => onChange({ ...value, [k]: v });
  const age = THIS_YEAR - value.birth_year;
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field label="First name" htmlFor="m-name">
        <TextInput id="m-name" value={value.name} onChange={(e) => set("name", e.target.value)} required />
      </Field>
      <Field label="Year born" htmlFor="m-born" hint={`About ${age} years old`}>
        <NumberInput id="m-born" value={value.birth_year} step={1} min={1920} max={THIS_YEAR - 18} onChange={(v) => set("birth_year", v ?? value.birth_year)} />
      </Field>
      <Field label="Age to stop working" htmlFor="m-retire"
        help="If already retired, enter your current age or the age you retired. Pay stops the year you reach this age."
        hint={value.retirement_age <= age ? "Already retired" : `In ${value.birth_year + value.retirement_age}`}>
        <NumberInput id="m-retire" value={value.retirement_age} step={1} min={40} max={85} onChange={(v) => set("retirement_age", v ?? 65)} />
      </Field>
      <Field label="Plan until age" htmlFor="m-life"
        help="How long the plan should last. Planning to 90-95 gives a cushion, because about 1 in 4 people who reach 65 live past 90.">
        <NumberInput id="m-life" value={value.life_expectancy} step={1} min={Math.max(age + 1, 60)} max={110} onChange={(v) => set("life_expectancy", v ?? 92)} />
      </Field>
      <Field label="Social Security, per month" htmlFor="m-ss"
        help={<>Find this on your Social Security statement at <strong>ssa.gov/myaccount</strong>. Use the amount shown &quot;at full retirement age&quot; (66-67). Enter 0 if you will not get Social Security.</>}
        hint="The amount at full retirement age, from your statement">
        <MoneyInput id="m-ss" value={value.ss_monthly_benefit} onChange={(v) => set("ss_monthly_benefit", v ?? 0)} />
      </Field>
      <Field label="Age to start Social Security" htmlFor="m-claim"
        help="You can start between 62 and 70. Each year you wait makes every monthly payment bigger (about 7-8% more per year).">
        <Select id="m-claim" value={String(value.ss_claim_age)} onChange={(v) => set("ss_claim_age", Number(v))}
          options={[62, 63, 64, 65, 66, 67, 68, 69, 70].map((a) => ({ value: String(a), label: `${a}${a === 67 ? " (full amount for most people)" : a === 70 ? " (largest payments)" : a === 62 ? " (earliest, smallest payments)" : ""}` }))} />
      </Field>
      {value.ss_claim_age <= age && value.ss_monthly_benefit > 0 && (
        <div className="sm:col-span-2">
          <Toggle checked={value.ss_basis === "as_claimed"} onChange={(v) => set("ss_basis", v ? "as_claimed" : "at_fra")}
            label="I already receive Social Security, and the amount above is what I get now"
            description="Turn this on if you entered your actual current payment rather than the full-retirement-age amount." />
        </div>
      )}
    </div>
  );
}

export function MemberForm({ member, kind, onSaved, onCancel }: {
  member?: MemberRow; kind: "self" | "spouse"; onSaved: (m: MemberRow) => void; onCancel?: () => void;
}) {
  const [draft, setDraft] = useState<MemberDraft>(() => (member ? { ...member } : blankMember(kind)));
  const s = useSave(
    () => (member ? api.put<MemberRow>(`/members/${member.id}`, draft) : api.post<MemberRow>("/members", draft)),
    onSaved,
  );
  return (
    <form onSubmit={s.submit} className="flex flex-col gap-4">
      <MemberFields value={draft} onChange={setDraft} />
      <ErrorBox error={s.error} />
      <Actions busy={s.busy} onCancel={onCancel} />
    </form>
  );
}

// ----------------------------------------------------------------------------- accounts

export const MIX_OPTIONS = [
  { value: "cash", label: "Cash only (savings, CDs)" },
  { value: "conservative", label: "Careful: mostly bonds (about 30% stocks)" },
  { value: "balanced", label: "Balanced: about 60% stocks, 40% bonds" },
  { value: "growth", label: "Growth: about 80% stocks" },
  { value: "aggressive", label: "Aggressive: about 95% stocks" },
];

type AccountDraft = {
  name: string;
  tax_type: AccountRow["tax_type"];
  member_id: string | null;
  institution: string | null;
  balance: number;
  cost_basis: number | null;
  annual_contribution: number;
  employer_match: number;
  annual_fee: number;
  allocation_preset: string | null;
};

export function AccountForm({ account, members, onSaved, onCancel, compact }: {
  account?: AccountRow; members: MemberRow[]; onSaved: (a: AccountRow) => void; onCancel?: () => void; compact?: boolean;
}) {
  const [d, setD] = useState<AccountDraft>(() => ({
    name: account?.name ?? "",
    tax_type: account?.tax_type ?? "traditional",
    member_id: account?.member_id ?? members[0]?.id ?? null,
    institution: account?.institution ?? null,
    balance: account?.balance ?? 0,
    cost_basis: account?.cost_basis ?? null,
    annual_contribution: account?.annual_contribution ?? 0,
    employer_match: account?.employer_match ?? 0,
    annual_fee: account?.annual_fee ?? 0,
    allocation_preset: account?.allocation_preset ?? (account ? null : "balanced"),
  }));
  const set = <K extends keyof AccountDraft>(k: K, v: AccountDraft[K]) => setD((x) => ({ ...x, [k]: v }));
  const personal = d.tax_type === "traditional" || d.tax_type === "roth" || d.tax_type === "hsa";
  const hasHoldings = !!account?.has_holdings;
  const s = useSave(() => {
    const body = {
      ...d,
      member_id: personal ? d.member_id : d.member_id || null,
      allocation_preset: d.tax_type === "cash" ? "cash" : d.allocation_preset,
    };
    return account ? api.put<AccountRow>(`/accounts/${account.id}`, body) : api.post<AccountRow>("/accounts", body);
  }, onSaved);
  const ownerOptions = [
    ...(personal ? [] : [{ value: "", label: "Joint / shared" }]),
    ...members.map((m) => ({ value: m.id, label: m.name })),
  ];
  return (
    <form onSubmit={s.submit} className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Type of account" htmlFor="a-type" hint={TAX_TYPE_HELP[d.tax_type]}>
          <Select id="a-type" value={d.tax_type} onChange={(v) => set("tax_type", v as AccountDraft["tax_type"])}
            options={Object.entries(TAX_TYPE_LABEL).map(([value, label]) => ({ value, label }))} />
        </Field>
        <Field label="Name" htmlFor="a-name" hint="Anything that helps you recognise it, e.g. 'Fidelity 401(k)'">
          <TextInput id="a-name" value={d.name} onChange={(e) => set("name", e.target.value)} required />
        </Field>
        <Field label="Whose account" htmlFor="a-owner">
          <Select id="a-owner" value={d.member_id ?? ""} onChange={(v) => set("member_id", v || null)} options={ownerOptions} />
        </Field>
        <Field label="Current balance" htmlFor="a-bal" hint={hasHoldings ? "Calculated from the investments listed in this account" : "From your latest statement"}>
          {hasHoldings ? <TextInput id="a-bal" disabled value={`$${account!.value.toLocaleString()}`} /> :
            <MoneyInput id="a-bal" value={d.balance} onChange={(v) => set("balance", v ?? 0)} />}
        </Field>
        {d.tax_type !== "cash" && !hasHoldings && (
          <Field label="How it is invested" htmlFor="a-mix" help="Stocks grow more over time but go up and down a lot. Bonds are steadier. If you are not sure, check your statement or choose Balanced.">
            <Select id="a-mix" value={d.allocation_preset ?? "custom"} onChange={(v) => set("allocation_preset", v === "custom" ? null : v)}
              options={[...MIX_OPTIONS.filter((o) => o.value !== "cash"), ...(d.allocation_preset ? [] : [{ value: "custom", label: "Custom (set earlier)" }])]} />
          </Field>
        )}
        {!compact && d.tax_type === "taxable" && !hasHoldings && (
          <Field label="What you paid in (cost basis)" htmlFor="a-basis" help="The total you originally invested. Only the growth above this is taxed when you sell. Leave blank if unsure; we will assume no gain.">
            <MoneyInput id="a-basis" value={d.cost_basis} allowEmpty onChange={(v) => set("cost_basis", v)} placeholder="Not sure" />
          </Field>
        )}
        {!compact && d.tax_type !== "cash" && (
          <>
            <Field label="You add each year" htmlFor="a-contrib" hint="Until retirement. 0 if nothing.">
              <MoneyInput id="a-contrib" value={d.annual_contribution} onChange={(v) => set("annual_contribution", v ?? 0)} />
            </Field>
            {d.tax_type !== "taxable" && (
              <Field label="Employer adds each year" htmlFor="a-match" hint="Company match, if any.">
                <MoneyInput id="a-match" value={d.employer_match} onChange={(v) => set("employer_match", v ?? 0)} />
              </Field>
            )}
            <Field label="Yearly fees" htmlFor="a-fee" help="Fund and advisor fees, as a percent of the balance per year. Index funds are often 0.05%-0.2%. Leave at 0 if unsure.">
              <PercentInput id="a-fee" value={d.annual_fee} min={0} max={0.05} onChange={(v) => set("annual_fee", v)} />
            </Field>
          </>
        )}
        {!compact && (
          <Field label="Bank or company (optional)" htmlFor="a-inst">
            <TextInput id="a-inst" value={d.institution ?? ""} onChange={(e) => set("institution", e.target.value || null)} />
          </Field>
        )}
      </div>
      <ErrorBox error={s.error} />
      <Actions busy={s.busy} onCancel={onCancel} label={account ? "Save" : "Add account"} />
    </form>
  );
}

// ----------------------------------------------------------------------------- income & expenses

export interface IncomeRow {
  id: string;
  name: string;
  member_id: string | null;
  kind: string;
  amount: number;
  start_year: number | null;
  end_year: number | null;
  ends_at_retirement: boolean;
  growth_mode: string;
  growth_rate: number;
  tax_treatment: string;
  survivor_pct: number;
}

export function IncomeForm({ income, members, onSaved, onCancel }: {
  income?: IncomeRow; members: MemberRow[]; onSaved: () => void; onCancel?: () => void;
}) {
  const [d, setD] = useState(() => ({
    name: income?.name ?? "",
    member_id: income?.member_id ?? members[0]?.id ?? null,
    kind: income?.kind ?? "salary",
    amount: income?.amount ?? 0,
    start_year: income?.start_year ?? null,
    end_year: income?.end_year ?? null,
    ends_at_retirement: income?.ends_at_retirement ?? true,
    growth_mode: income?.growth_mode ?? "inflation",
    growth_rate: income?.growth_rate ?? 0,
    tax_treatment: income?.tax_treatment ?? "earned",
    survivor_pct: income?.survivor_pct ?? 0,
  }));
  const set = (k: string, v: unknown) => setD((x) => ({ ...x, [k]: v }));
  const isPay = d.kind === "salary" || d.kind === "business";
  const s = useSave(async () => {
    const body = { ...d, tax_treatment: d.kind === "salary" ? "earned" : d.tax_treatment === "earned" ? "ordinary" : d.tax_treatment,
      ends_at_retirement: d.kind === "salary" ? d.ends_at_retirement : false };
    return income ? api.put(`/incomes/${income.id}`, body) : api.post("/incomes", body);
  }, onSaved);
  return (
    <form onSubmit={s.submit} className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Kind of income" htmlFor="i-kind">
          <Select id="i-kind" value={d.kind} onChange={(v) => set("kind", v)} options={[
            { value: "salary", label: "Pay from a job" },
            { value: "annuity", label: "Annuity" },
            { value: "rental", label: "Rent from a property" },
            { value: "business", label: "Self-employment / business" },
            { value: "other", label: "Other" },
          ]} />
        </Field>
        <Field label="Name" htmlFor="i-name">
          <TextInput id="i-name" value={d.name} onChange={(e) => set("name", e.target.value)} required placeholder="e.g. My job" />
        </Field>
        <Field label="Whose income" htmlFor="i-owner">
          <Select id="i-owner" value={d.member_id ?? ""} onChange={(v) => set("member_id", v || null)}
            options={[...(d.kind === "salary" ? [] : [{ value: "", label: "Joint / shared" }]), ...members.map((m) => ({ value: m.id, label: m.name }))]} />
        </Field>
        <Field label="Amount per year (before tax)" htmlFor="i-amt">
          <MoneyInput id="i-amt" value={d.amount} onChange={(v) => set("amount", v ?? 0)} />
        </Field>
        {d.kind === "salary" && (
          <div className="sm:col-span-2">
            <Toggle checked={d.ends_at_retirement} onChange={(v) => set("ends_at_retirement", v)} label="Stops when this person retires" />
          </div>
        )}
        <Field label="Starts in year (optional)" htmlFor="i-start" hint="Leave blank if it is already coming in">
          <NumberInput id="i-start" value={d.start_year} allowEmpty step={1} onChange={(v) => set("start_year", v)} />
        </Field>
        <Field label="Last year paid (optional)" htmlFor="i-end" hint="Leave blank if it continues for life">
          <NumberInput id="i-end" value={d.end_year} allowEmpty step={1} onChange={(v) => set("end_year", v)} />
        </Field>
        <Field label="Does it rise with prices?" htmlFor="i-grow">
          <Select id="i-grow" value={d.growth_mode} onChange={(v) => set("growth_mode", v)} options={[
            { value: "inflation", label: "Yes, it keeps up with rising prices" },
            { value: "none", label: "No, it stays the same amount" },
            { value: "fixed", label: "It grows by a set percent" },
          ]} />
        </Field>
        {d.growth_mode === "fixed" && (
          <Field label="Yearly growth" htmlFor="i-rate">
            <PercentInput id="i-rate" value={d.growth_rate} onChange={(v) => set("growth_rate", v)} />
          </Field>
        )}
        {!isPay && (
          <Field label="Is it taxed?" htmlFor="i-tax">
            <Select id="i-tax" value={d.tax_treatment === "tax_free" ? "tax_free" : "ordinary"} onChange={(v) => set("tax_treatment", v)} options={[
              { value: "ordinary", label: "Yes, it is taxable income" },
              { value: "tax_free", label: "No, it is tax-free" },
            ]} />
          </Field>
        )}
      </div>
      <ErrorBox error={s.error} />
      <Actions busy={s.busy} onCancel={onCancel} />
    </form>
  );
}

export interface PensionRow {
  id: string;
  name: string;
  member_id: string;
  annual_amount: number;
  start_age: number;
  has_cola: boolean;
  survivor_pct: number;
}

export function PensionForm({ pension, members, onSaved, onCancel }: {
  pension?: PensionRow; members: MemberRow[]; onSaved: () => void; onCancel?: () => void;
}) {
  const [d, setD] = useState(() => ({
    name: pension?.name ?? "Pension",
    member_id: pension?.member_id ?? members[0]?.id ?? "",
    annual_amount: pension?.annual_amount ?? 0,
    start_age: pension?.start_age ?? 65,
    has_cola: pension?.has_cola ?? false,
    survivor_pct: pension?.survivor_pct ?? 0.5,
  }));
  const set = (k: string, v: unknown) => setD((x) => ({ ...x, [k]: v }));
  const s = useSave(async () => (pension ? api.put(`/pensions/${pension.id}`, d) : api.post("/pensions", d)), onSaved);
  return (
    <form onSubmit={s.submit} className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Name" htmlFor="p-name"><TextInput id="p-name" value={d.name} onChange={(e) => set("name", e.target.value)} required /></Field>
        <Field label="Whose pension" htmlFor="p-owner">
          <Select id="p-owner" value={d.member_id} onChange={(v) => set("member_id", v)} options={members.map((m) => ({ value: m.id, label: m.name }))} />
        </Field>
        <Field label="Amount per year (before tax)" htmlFor="p-amt"><MoneyInput id="p-amt" value={d.annual_amount} onChange={(v) => set("annual_amount", v ?? 0)} /></Field>
        <Field label="Starts at age" htmlFor="p-age"><NumberInput id="p-age" value={d.start_age} step={1} min={40} max={100} onChange={(v) => set("start_age", v ?? 65)} /></Field>
        <Field label="After this person dies, the survivor keeps" htmlFor="p-surv" help="Many pensions continue at 50% or 100% to a surviving spouse. Check your pension paperwork.">
          <PercentInput id="p-surv" value={d.survivor_pct} min={0} max={1} onChange={(v) => set("survivor_pct", v)} />
        </Field>
        <div className="flex items-end pb-2">
          <Toggle checked={d.has_cola} onChange={(v) => set("has_cola", v)} label="Rises with prices each year (COLA)" />
        </div>
      </div>
      <ErrorBox error={s.error} />
      <Actions busy={s.busy} onCancel={onCancel} />
    </form>
  );
}

export interface ExpenseRow {
  id: string;
  name: string;
  amount: number;
  category: "essential" | "discretionary";
  kind: string;
  start_year: number | null;
  end_year: number | null;
  starts_at_retirement: boolean;
  ends_at_retirement: boolean;
  inflation_mode: string;
  custom_rate: number;
  survivor_pct: number | null;
}

export function ExpenseForm({ expense, onSaved, onCancel, oneTime }: {
  expense?: ExpenseRow; onSaved: () => void; onCancel?: () => void; oneTime?: boolean;
}) {
  const [monthly, setMonthly] = useState(false);
  const [d, setD] = useState(() => ({
    name: expense?.name ?? "",
    amount: expense?.amount ?? 0,
    category: expense?.category ?? "essential",
    kind: expense?.kind ?? (oneTime ? "one_time" : "living"),
    start_year: expense?.start_year ?? (oneTime ? THIS_YEAR + 1 : null),
    end_year: expense?.end_year ?? null,
    starts_at_retirement: expense?.starts_at_retirement ?? false,
    ends_at_retirement: expense?.ends_at_retirement ?? false,
    inflation_mode: expense?.inflation_mode ?? "general",
    custom_rate: expense?.custom_rate ?? 0,
    survivor_pct: expense?.survivor_pct ?? null,
  }));
  const set = (k: string, v: unknown) => setD((x) => ({ ...x, [k]: v }));
  const isOnce = d.kind === "one_time";
  const s = useSave(async () => {
    const body = { ...d, inflation_mode: d.kind === "healthcare" && d.inflation_mode === "general" ? "healthcare" : d.inflation_mode };
    return expense ? api.put(`/expenses/${expense.id}`, body) : api.post("/expenses", body);
  }, onSaved);
  return (
    <form onSubmit={s.submit} className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="What is it for?" htmlFor="e-name">
          <TextInput id="e-name" value={d.name} onChange={(e) => set("name", e.target.value)} required placeholder={isOnce ? "e.g. New car" : "e.g. Groceries and bills"} />
        </Field>
        <Field label={isOnce ? "Cost" : monthly ? "Amount per month" : "Amount per year"} htmlFor="e-amt"
          hint={!isOnce && <button type="button" className="underline" onClick={() => setMonthly(!monthly)}>{monthly ? "Enter per year instead" : "Enter per month instead"}</button>}>
          <MoneyInput id="e-amt" value={monthly ? Math.round(d.amount / 12) : d.amount} onChange={(v) => set("amount", (v ?? 0) * (monthly ? 12 : 1))} />
        </Field>
        {!isOnce && (
          <Field label="Must-have or nice-to-have?" htmlFor="e-cat"
            help="Must-haves (housing, food, bills, insurance) are never cut. Nice-to-haves (travel, hobbies, gifts) could be trimmed in a bad year if you turn on spending guardrails.">
            <Select id="e-cat" value={d.category} onChange={(v) => set("category", v)} options={[
              { value: "essential", label: "Must-have (essential)" },
              { value: "discretionary", label: "Nice-to-have (optional)" },
            ]} />
          </Field>
        )}
        <Field label="Kind" htmlFor="e-kind">
          <Select id="e-kind" value={d.kind} onChange={(v) => set("kind", v)} options={[
            { value: "living", label: "Everyday living" },
            { value: "housing", label: "Housing (rent, property tax, insurance)" },
            { value: "healthcare", label: "Health costs (premiums, out of pocket)" },
            { value: "one_time", label: "One-time cost (a single year)" },
            { value: "other", label: "Other" },
          ]} />
        </Field>
        {isOnce ? (
          <Field label="In which year?" htmlFor="e-year">
            <NumberInput id="e-year" value={d.start_year} step={1} min={THIS_YEAR} max={THIS_YEAR + 60} onChange={(v) => setD((x) => ({ ...x, start_year: v, end_year: v }))} />
          </Field>
        ) : (
          <>
            <Field label="When does it start?" htmlFor="e-when">
              <Select id="e-when" value={d.starts_at_retirement ? "retire" : d.start_year ? "year" : "now"} onChange={(v) => setD((x) => ({
                ...x, starts_at_retirement: v === "retire", start_year: v === "year" ? (x.start_year ?? THIS_YEAR + 1) : null,
              }))} options={[
                { value: "now", label: "Now" },
                { value: "retire", label: "When everyone has retired" },
                { value: "year", label: "In a specific year" },
              ]} />
            </Field>
            {d.start_year !== null && !d.starts_at_retirement && (
              <Field label="Start year" htmlFor="e-sy"><NumberInput id="e-sy" value={d.start_year} step={1} onChange={(v) => set("start_year", v)} /></Field>
            )}
            <Field label="When does it end?" htmlFor="e-end">
              <Select id="e-end" value={d.ends_at_retirement ? "retire" : d.end_year ? "year" : "never"} onChange={(v) => setD((x) => ({
                ...x, ends_at_retirement: v === "retire", end_year: v === "year" ? (x.end_year ?? THIS_YEAR + 10) : null,
              }))} options={[
                { value: "never", label: "It continues for life" },
                { value: "retire", label: "When everyone has retired" },
                { value: "year", label: "After a specific year" },
              ]} />
            </Field>
            {d.end_year !== null && !d.ends_at_retirement && (
              <Field label="Last year" htmlFor="e-ey"><NumberInput id="e-ey" value={d.end_year} step={1} onChange={(v) => set("end_year", v)} /></Field>
            )}
            <Field label="Does it rise with prices?" htmlFor="e-infl">
              <Select id="e-infl" value={d.inflation_mode} onChange={(v) => set("inflation_mode", v)} options={[
                { value: "general", label: "Yes, like everyday prices" },
                { value: "healthcare", label: "Yes, faster (like health costs)" },
                { value: "none", label: "No, fixed amount (e.g. a fixed loan payment)" },
                { value: "custom", label: "By a set percent" },
              ]} />
            </Field>
            {d.inflation_mode === "custom" && (
              <Field label="Yearly increase" htmlFor="e-rate"><PercentInput id="e-rate" value={d.custom_rate} onChange={(v) => set("custom_rate", v)} /></Field>
            )}
          </>
        )}
      </div>
      <ErrorBox error={s.error} />
      <Actions busy={s.busy} onCancel={onCancel} />
    </form>
  );
}
