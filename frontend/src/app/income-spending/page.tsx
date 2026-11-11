"use client";

import { useState, type ReactNode } from "react";
import { ExpenseForm, IncomeForm, MemberForm, PensionForm, type ExpenseRow, type IncomeRow, type PensionRow } from "@/components/forms";
import { useSession } from "@/components/session";
import { Badge, Button, Card, ErrorBox, Loading, Modal, PageHeader, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { money } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { MemberRow } from "@/lib/types";

type Editing =
  | { kind: "member"; row?: MemberRow; as: "self" | "spouse" }
  | { kind: "income"; row?: IncomeRow }
  | { kind: "pension"; row?: PensionRow }
  | { kind: "expense"; row?: ExpenseRow; oneTime?: boolean };

export default function IncomeSpending() {
  const { refresh } = useSession();
  const members = useApi<MemberRow[]>("/members");
  const incomes = useApi<IncomeRow[]>("/incomes");
  const pensions = useApi<PensionRow[]>("/pensions");
  const expenses = useApi<ExpenseRow[]>("/expenses");
  const [editing, setEditing] = useState<Editing | null>(null);
  const year = new Date().getFullYear();

  const done = () => {
    setEditing(null);
    members.reload();
    incomes.reload();
    pensions.reload();
    expenses.reload();
    refresh();
  };

  async function remove(path: string, name: string) {
    if (!window.confirm(`Remove "${name}"?`)) return;
    await api.del(path);
    done();
  }

  const ms = members.data ?? [];
  const nameOf = (id: string | null) => ms.find((m) => m.id === id)?.name ?? "Joint";
  const regular = (expenses.data ?? []).filter((e) => e.kind !== "one_time");
  const oneTime = (expenses.data ?? []).filter((e) => e.kind === "one_time");
  const activeNow = (e: ExpenseRow) => !e.starts_at_retirement && (e.start_year ?? year) <= year && (e.end_year ?? year) >= year;
  const essentialNow = regular.filter((e) => e.category === "essential" && activeNow(e)).reduce((s, e) => s + e.amount, 0);
  const optionalNow = regular.filter((e) => e.category === "discretionary" && activeNow(e)).reduce((s, e) => s + e.amount, 0);
  const ssTotal = ms.reduce((s, m) => s + m.ss_monthly_benefit * 12, 0);

  if (members.loading && !members.data) return <Loading />;

  return (
    <>
      <PageHeader title="Income & spending" intro="The people in your plan, money coming in, and money going out. All amounts are in today's dollars; the plan adjusts them for rising prices." />
      <ErrorBox error={members.error} />

      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <Stat label="Must-have spending (this year)" value={money(essentialNow)} sub="per year" />
        <Stat label="Nice-to-have spending (this year)" value={money(optionalNow)} sub="per year" />
        <Stat label="Social Security (full amount)" value={money(ssTotal)} sub="per year, all people" />
      </div>

      <Section title="People" action={ms.length < 2 && <Button variant="secondary" onClick={() => setEditing({ kind: "member", as: ms.length ? "spouse" : "self" })}>+ Add {ms.length ? "spouse or partner" : "person"}</Button>}>
        {ms.map((m) => (
          <Item key={m.id} title={m.name} detail={<>
            Age {m.age} · {m.retirement_age <= m.age ? "retired" : `retires at ${m.retirement_age} (${m.birth_year + m.retirement_age})`} · plan to age {m.life_expectancy}
            <br />Social Security {money(m.ss_monthly_benefit)}/month {m.ss_basis === "as_claimed" ? "(current payment)" : "at full retirement age"}, starting at {m.ss_claim_age}
          </>} onEdit={() => setEditing({ kind: "member", row: m, as: m.relationship_kind })}
            onRemove={ms.length > 1 ? () => remove(`/members/${m.id}`, m.name) : undefined} />
        ))}
      </Section>

      <Section title="Income" subtitle="Pay, annuities, rent and other income. Social Security is set per person above."
        action={<>
          <Button variant="secondary" onClick={() => setEditing({ kind: "income" })}>+ Income</Button>
          <Button variant="secondary" onClick={() => setEditing({ kind: "pension" })}>+ Pension</Button>
        </>}>
        {!incomes.data?.length && !pensions.data?.length && <p className="text-muted">No income added.</p>}
        {incomes.data?.map((i) => (
          <Item key={i.id} title={i.name} amount={`${money(i.amount)} / yr`}
            detail={<>{nameOf(i.member_id)} · {i.kind === "salary" ? "pay" : i.kind}
              {i.ends_at_retirement ? " · stops at retirement" : i.end_year ? ` · until ${i.end_year}` : ""}
              {i.start_year ? ` · from ${i.start_year}` : ""}
              {i.growth_mode === "none" ? " · fixed amount" : ""}</>}
            onEdit={() => setEditing({ kind: "income", row: i })} onRemove={() => remove(`/incomes/${i.id}`, i.name)} />
        ))}
        {pensions.data?.map((p) => (
          <Item key={p.id} title={p.name} amount={`${money(p.annual_amount)} / yr`}
            detail={<>{nameOf(p.member_id)} · pension from age {p.start_age}{p.has_cola ? " · rises with prices" : " · fixed amount"} · survivor keeps {Math.round(p.survivor_pct * 100)}%</>}
            onEdit={() => setEditing({ kind: "pension", row: p })} onRemove={() => remove(`/pensions/${p.id}`, p.name)} />
        ))}
      </Section>

      <Section title="Regular spending" subtitle="Do not include taxes, savings or debt payments; the plan adds those itself."
        action={<Button variant="secondary" onClick={() => setEditing({ kind: "expense" })}>+ Spending</Button>}>
        {regular.length === 0 && <p className="text-muted">No spending added yet.</p>}
        {regular.map((e) => (
          <Item key={e.id} title={e.name} amount={`${money(e.amount)} / yr`}
            badge={<Badge tone={e.category === "essential" ? "brand" : "neutral"}>{e.category === "essential" ? "must-have" : "nice-to-have"}</Badge>}
            detail={<>{e.starts_at_retirement ? "from retirement" : e.start_year ? `from ${e.start_year}` : "now"}
              {e.ends_at_retirement ? " until retirement" : e.end_year ? ` until ${e.end_year}` : ""}
              {e.inflation_mode === "healthcare" ? " · rises like health costs" : e.inflation_mode === "none" ? " · fixed amount" : ""}</>}
            onEdit={() => setEditing({ kind: "expense", row: e })} onRemove={() => remove(`/expenses/${e.id}`, e.name)} />
        ))}
      </Section>

      <Section title="One-time costs" subtitle="Big single expenses: a new car, a roof, helping a child, a special trip."
        action={<Button variant="secondary" onClick={() => setEditing({ kind: "expense", oneTime: true })}>+ One-time cost</Button>}>
        {oneTime.length === 0 && <p className="text-muted">None planned.</p>}
        {oneTime.map((e) => (
          <Item key={e.id} title={e.name} amount={money(e.amount)} detail={<>In {e.start_year}</>}
            onEdit={() => setEditing({ kind: "expense", row: e })} onRemove={() => remove(`/expenses/${e.id}`, e.name)} />
        ))}
      </Section>

      <Modal open={editing !== null} onClose={() => setEditing(null)} wide
        title={editing?.kind === "member" ? (editing.row ? `Edit ${editing.row.name}` : "Add a person") : editing?.kind === "income" ? "Income" : editing?.kind === "pension" ? "Pension" : "Spending"}>
        {editing?.kind === "member" && <MemberForm member={editing.row} kind={editing.as} onSaved={done} onCancel={() => setEditing(null)} />}
        {editing?.kind === "income" && <IncomeForm income={editing.row} members={ms} onSaved={done} onCancel={() => setEditing(null)} />}
        {editing?.kind === "pension" && <PensionForm pension={editing.row} members={ms} onSaved={done} onCancel={() => setEditing(null)} />}
        {editing?.kind === "expense" && <ExpenseForm expense={editing.row} oneTime={editing.oneTime} onSaved={done} onCancel={() => setEditing(null)} />}
      </Modal>
    </>
  );
}

function Section({ title, subtitle, action, children }: { title: string; subtitle?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <Card title={title} subtitle={subtitle} actions={action} className="mb-6">
      <ul className="divide-y divide-line">{children}</ul>
    </Card>
  );
}

function Item({ title, detail, amount, badge, onEdit, onRemove }: {
  title: string; detail?: ReactNode; amount?: string; badge?: ReactNode; onEdit: () => void; onRemove?: () => void;
}) {
  return (
    <li className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <p className="font-semibold">{title} {badge}</p>
        {detail && <p className="text-sm text-muted">{detail}</p>}
      </div>
      <div className="flex items-center gap-1">
        {amount && <span className="mr-2 font-semibold tabular-nums">{amount}</span>}
        <Button variant="ghost" onClick={onEdit}>Edit</Button>
        {onRemove && <Button variant="ghost" onClick={onRemove}>Remove</Button>}
      </div>
    </li>
  );
}
