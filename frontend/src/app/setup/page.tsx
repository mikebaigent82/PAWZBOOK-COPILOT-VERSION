"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { AccountForm, blankMember, ExpenseForm, IncomeForm, MemberFields, PensionForm, type MemberDraft } from "@/components/forms";
import { useSession } from "@/components/session";
import { Button, Card, cx, ErrorBox, Field, Loading, Notice, PageHeader, Select, Toggle } from "@/components/ui";
import { api } from "@/lib/api";
import { money, TAX_TYPE_LABEL } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { AccountRow, MemberRow } from "@/lib/types";

const STEPS = ["Start", "About you", "Savings", "Income", "Spending", "Done"];

export default function Setup() {
  const { household, refresh } = useSession();
  const router = useRouter();
  const [step, setStep] = useState(household.member_count ? 1 : 0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function sample() {
    setBusy(true);
    setError(null);
    try {
      await api.post("/sample-data");
      await refresh();
      router.push("/");
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  async function finish() {
    await api.patch("/household", { onboarding_complete: true });
    await refresh();
    router.push("/");
  }

  return (
    <>
      <PageHeader title="Set up your plan" intro="Answer a few questions. You can change anything later, and nothing is shared with anyone." />
      <ol className="mb-6 flex flex-wrap gap-2" aria-label="Steps">
        {STEPS.map((s, i) => (
          <li key={s}>
            <button
              type="button"
              disabled={i > 0 && !household.member_count && i !== step}
              onClick={() => setStep(i)}
              aria-current={i === step ? "step" : undefined}
              className={cx(
                "min-h-9 rounded-full border px-3 text-sm font-medium",
                i === step ? "border-brand bg-brand text-white" : i < step ? "border-brand/40 bg-brand-soft text-brand-dark" : "border-line bg-white text-muted",
              )}
            >
              {i + 1}. {s}
            </button>
          </li>
        ))}
      </ol>

      {step === 0 && (
        <div className="grid gap-4 md:grid-cols-2">
          <Card title="Enter my own details">
            <p className="text-muted">About 10 minutes. Have your latest account statements and your Social Security statement (from ssa.gov) nearby if you can, but rough numbers are fine to start.</p>
            <Button className="mt-4" onClick={() => setStep(1)}>Start</Button>
          </Card>
          <Card title="Look around with sample data first">
            <p className="text-muted">Loads a made-up couple so you can see how everything works. You can clear it later and enter your own.</p>
            <Button variant="secondary" className="mt-4" busy={busy} onClick={sample}>Load sample data</Button>
            <ErrorBox error={error} />
          </Card>
        </div>
      )}
      {step === 1 && <PeopleStep onNext={async () => { await refresh(); setStep(2); }} />}
      {step === 2 && <SavingsStep onBack={() => setStep(1)} onNext={() => setStep(3)} />}
      {step === 3 && <IncomeStep onBack={() => setStep(2)} onNext={() => setStep(4)} />}
      {step === 4 && <SpendingStep onBack={() => setStep(3)} onNext={() => setStep(5)} />}
      {step === 5 && (
        <Card title="All set">
          <p className="text-muted">Your plan is ready. Next, we will check it in 1,000 possible futures and tell you in plain English how it looks.</p>
          <div className="mt-4 flex gap-2">
            <Button onClick={finish}>See my results</Button>
            <Button variant="secondary" onClick={() => setStep(4)}>Back</Button>
          </div>
        </Card>
      )}
    </>
  );
}

function PeopleStep({ onNext }: { onNext: () => void }) {
  const { household } = useSession();
  const members = useApi<MemberRow[]>("/members");
  if (members.loading || !members.data) return <Loading />;
  return <PeopleEditor key={members.data.map((m) => m.id).join()} existing={members.data} household={household} onNext={onNext} />;
}

function PeopleEditor({ existing, household, onNext }: {
  existing: MemberRow[]; household: ReturnType<typeof useSession>["household"]; onNext: () => void;
}) {
  const self = existing.find((m) => m.relationship_kind === "self") ?? existing[0];
  const spouse = existing.find((m) => m !== self);
  const [me, setMe] = useState<MemberDraft>(self ? { ...self } : blankMember("self"));
  const [hasSpouse, setHasSpouse] = useState(!!spouse);
  const [sp, setSp] = useState<MemberDraft>(spouse ? { ...spouse } : blankMember("spouse"));
  const [married, setMarried] = useState(household.filing_status === "mfj" || (!!spouse && household.filing_status !== "single"));
  const [state, setState] = useState(household.state);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (self) await api.put(`/members/${self.id}`, me);
      else await api.post("/members", { ...me, relationship_kind: "self" });
      if (hasSpouse) {
        if (spouse) await api.put(`/members/${spouse.id}`, sp);
        else await api.post("/members", { ...sp, relationship_kind: "spouse" });
      } else if (spouse) {
        await api.del(`/members/${spouse.id}`);
      }
      await api.patch("/household", { state, filing_status: hasSpouse && married ? "mfj" : "single" });
      onNext();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="flex flex-col gap-6">
      <Card title="About you">
        <MemberFields value={me} onChange={setMe} />
      </Card>
      <Card title="Your spouse or partner">
        <Toggle checked={hasSpouse} onChange={setHasSpouse} label="Include a spouse or partner in this plan" />
        {hasSpouse && (
          <div className="mt-4 flex flex-col gap-4">
            <MemberFields value={sp} onChange={setSp} />
            <Toggle checked={married} onChange={setMarried} label="We are married and file taxes jointly" />
          </div>
        )}
      </Card>
      <Card title="Where you live">
        <Field label="State" htmlFor="state" help="Used for state income tax. Some states have none.">
          <Select id="state" className="max-w-xs" value={state} onChange={setState} options={household.states.map((s) => ({ value: s, label: s }))} />
        </Field>
        {household.no_income_tax_states.includes(state) ? (
          <p className="mt-2 text-sm text-muted">{state} has no state income tax on wages and retirement income.</p>
        ) : (
          <p className="mt-2 text-sm text-muted">State tax is estimated with a simple average rate (4% to start). You can set your own rate under Settings.</p>
        )}
      </Card>
      <ErrorBox error={error} />
      <div><Button type="submit" busy={busy}>Save and continue</Button></div>
    </form>
  );
}

function ListStep<T extends { id: string }>({ title, intro, items, render, form, addLabel, onBack, onNext, empty }: {
  title: string; intro: string; items: T[] | null; render: (t: T) => React.ReactNode; form: (done: () => void) => React.ReactNode;
  addLabel: string; onBack: () => void; onNext: () => void; empty: string;
}) {
  const [adding, setAdding] = useState(false);
  return (
    <div className="flex flex-col gap-6">
      <Card title={title} subtitle={intro}>
        {!items ? <Loading /> : items.length === 0 ? <p className="text-muted">{empty}</p> : (
          <ul className="divide-y divide-line">{items.map((t) => <li key={t.id} className="py-2">{render(t)}</li>)}</ul>
        )}
        {adding ? <div className="mt-4 rounded-lg border border-line bg-paper p-4">{form(() => setAdding(false))}</div> :
          <Button variant="secondary" className="mt-4" onClick={() => setAdding(true)}>+ {addLabel}</Button>}
      </Card>
      <div className="flex gap-2">
        <Button onClick={onNext}>Continue</Button>
        <Button variant="secondary" onClick={onBack}>Back</Button>
      </div>
    </div>
  );
}

function SavingsStep({ onBack, onNext }: { onBack: () => void; onNext: () => void }) {
  const members = useApi<MemberRow[]>("/members");
  const accounts = useApi<AccountRow[]>("/accounts");
  return (
    <ListStep
      title="Your savings and investments"
      intro="Add each account: 401(k)s, IRAs, brokerage, bank savings. A rough balance is fine. You can also import a CSV file later on the My money page."
      items={accounts.data}
      empty="No accounts yet."
      addLabel="Add an account"
      render={(a) => (
        <div className="flex justify-between gap-4"><span><strong>{a.name}</strong> <span className="text-muted">· {TAX_TYPE_LABEL[a.tax_type]}</span></span><span className="tabular-nums">{money(a.value)}</span></div>
      )}
      form={(done) => members.data && <AccountForm compact members={members.data} onSaved={() => { accounts.reload(); done(); }} onCancel={done} />}
      onBack={onBack}
      onNext={onNext}
    />
  );
}

function IncomeStep({ onBack, onNext }: { onBack: () => void; onNext: () => void }) {
  const members = useApi<MemberRow[]>("/members");
  const incomes = useApi<{ id: string; name: string; amount: number; kind: string }[]>("/incomes");
  const pensions = useApi<{ id: string; name: string; annual_amount: number; start_age: number }[]>("/pensions");
  const [pensionOpen, setPensionOpen] = useState(false);
  return (
    <div className="flex flex-col gap-6">
      <Notice tone="info">Social Security was entered in the previous step. Add pay from work, pensions and any other income here.</Notice>
      <ListStep
        title="Pay and other income"
        intro="Pay from work stops automatically when that person retires."
        items={incomes.data}
        empty="No income added. That is fine if you are already retired."
        addLabel="Add income"
        render={(i) => <div className="flex justify-between"><strong>{i.name}</strong><span className="tabular-nums">{money(i.amount)} / year</span></div>}
        form={(done) => members.data && <IncomeForm members={members.data} onSaved={() => { incomes.reload(); done(); }} onCancel={done} />}
        onBack={onBack}
        onNext={onNext}
      />
      <Card title="Pensions" subtitle="A regular payment from a former employer.">
        {pensions.data?.length ? (
          <ul className="divide-y divide-line">{pensions.data.map((p) => (
            <li key={p.id} className="flex justify-between py-2"><strong>{p.name}</strong><span className="tabular-nums">{money(p.annual_amount)} / year from age {p.start_age}</span></li>
          ))}</ul>
        ) : <p className="text-muted">No pensions added.</p>}
        {pensionOpen ? <div className="mt-4 rounded-lg border border-line bg-paper p-4">
          {members.data && <PensionForm members={members.data} onSaved={() => { pensions.reload(); setPensionOpen(false); }} onCancel={() => setPensionOpen(false)} />}
        </div> : <Button variant="secondary" className="mt-4" onClick={() => setPensionOpen(true)}>+ Add a pension</Button>}
      </Card>
    </div>
  );
}

function SpendingStep({ onBack, onNext }: { onBack: () => void; onNext: () => void }) {
  const expenses = useApi<{ id: string; name: string; amount: number; category: string }[]>("/expenses");
  return (
    <ListStep
      title="What you spend"
      intro="A simple way to start: one line for must-haves (housing, food, bills, insurance) and one for nice-to-haves (travel, hobbies, gifts). Do not include taxes or savings; the plan works those out."
      items={expenses.data}
      empty="No spending added yet. The plan needs at least a rough figure."
      addLabel="Add spending"
      render={(e) => <div className="flex justify-between"><span><strong>{e.name}</strong> <span className="text-muted">· {e.category === "essential" ? "must-have" : "nice-to-have"}</span></span><span className="tabular-nums">{money(e.amount)} / year</span></div>}
      form={(done) => <ExpenseForm onSaved={() => { expenses.reload(); done(); }} onCancel={done} />}
      onBack={onBack}
      onNext={onNext}
    />
  );
}
