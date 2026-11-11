"use client";

import { useEffect, useState } from "react";
import { useSession } from "@/components/session";
import {
  Badge, Button, Card, ErrorBox, Field, Help, Loading, Modal, MoneyInput, Notice, NumberInput, PageHeader, PercentInput,
  Select, Table, TextInput, Toggle,
} from "@/components/ui";
import { api, saveBlob } from "@/lib/api";
import { dateText, pct } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Assumptions, AssetClassRow, PlanInfo } from "@/lib/types";

export default function Settings() {
  return (
    <>
      <PageHeader title="Settings" intro="Assumptions behind the numbers, account security, and your data." />
      <div className="flex flex-col gap-6">
        <AssumptionsCard />
        <ReturnsCard />
        <SecurityCard />
        <DataCard />
        <ActivityCard />
      </div>
    </>
  );
}

function AssumptionsCard() {
  const plan = useApi<PlanInfo>("/plan");
  const history = useApi<{ version: number; note: string | null; saved_at: string }[]>("/plan/assumptions/history");
  const [a, setA] = useState<Assumptions | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const [advanced, setAdvanced] = useState(false);

  useEffect(() => {
    if (plan.data) setA(structuredClone(plan.data.assumptions));
  }, [plan.data]);

  if (!plan.data || !a) return <Loading />;
  const d = plan.data.defaults;
  const set = <K extends keyof Assumptions>(k: K, v: Assumptions[K]) => { setA({ ...a, [k]: v }); setSaved(false); };

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const { state_tax, ...rest } = a!;
      await api.patch("/plan/assumptions", { changes: { ...rest, state_tax: { ...state_tax, state: plan.data!.assumptions.state_tax.state } }, note: "Changed in Settings" });
      setSaved(true);
      plan.reload();
      history.reload();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  const ssCut = a.ss_reduction_year !== null && a.ss_reduction_pct > 0;

  return (
    <Card title="Assumptions" subtitle={`Version ${plan.data.assumption_version}, saved ${dateText(plan.data.assumption_saved_at)}. Every change is kept, so earlier results can always be reproduced.`}>
      <div className="grid gap-5 md:grid-cols-2">
        <Field label="Inflation (rising prices)" htmlFor="infl" help={`How much prices rise each year. The usual long-run figure is 2-3%. Default ${pct(d.inflation, 1)}.`}>
          <PercentInput id="infl" value={a.inflation} min={0} max={0.15} onChange={(v) => set("inflation", v)} />
        </Field>
        <Field label="Health-cost inflation" htmlFor="hinfl" help={`Health costs and Medicare premiums usually rise faster than other prices. Default ${pct(d.healthcare_inflation, 1)}.`}>
          <PercentInput id="hinfl" value={a.healthcare_inflation} min={0} max={0.2} onChange={(v) => set("healthcare_inflation", v)} />
        </Field>
        <Field label="State income tax rate" htmlFor="st" help={plan.data.state_tax_note}>
          <PercentInput id="st" value={a.state_tax.rate} min={0} max={0.15} onChange={(v) => set("state_tax", { ...a.state_tax, rate: v })} />
        </Field>
        <div className="flex flex-col gap-3 pt-7">
          <Toggle checked={!a.state_tax.taxes_social_security} onChange={(v) => set("state_tax", { ...a.state_tax, taxes_social_security: !v })} label="My state does not tax Social Security" description="True for most states." />
          <Toggle checked={a.state_tax.exempts_retirement_income} onChange={(v) => set("state_tax", { ...a.state_tax, exempts_retirement_income: v })} label="My state does not tax pensions or IRA withdrawals" />
        </div>
        <Field label="Spending after one spouse dies" htmlFor="surv" help="Households usually spend somewhat less with one person. 70-80% of before is a common estimate.">
          <PercentInput id="surv" value={a.survivor_expense_pct} min={0} max={2} onChange={(v) => set("survivor_expense_pct", v)} />
        </Field>
        <div className="flex flex-col gap-3">
          <Toggle checked={ssCut} onChange={(v) => setA({ ...a, ss_reduction_pct: v ? 0.2 : 0, ss_reduction_year: v ? 2034 : null })}
            label="Assume Social Security payments are cut in the future"
            description="Government reports project the Social Security trust fund could run short in the 2030s. This lets you test a cut." />
          {ssCut && (
            <div className="grid grid-cols-2 gap-3">
              <Field label="Cut by" htmlFor="sscut"><PercentInput id="sscut" value={a.ss_reduction_pct} min={0} max={1} onChange={(v) => set("ss_reduction_pct", v)} /></Field>
              <Field label="Starting in" htmlFor="ssyear"><NumberInput id="ssyear" step={1} value={a.ss_reduction_year} onChange={(v) => set("ss_reduction_year", v)} /></Field>
            </div>
          )}
        </div>
        <div className="md:col-span-2 rounded-lg border border-line p-4">
          <Toggle checked={a.guardrails.enabled} onChange={(v) => set("guardrails", { ...a.guardrails, enabled: v })}
            label="Use spending guardrails"
            description="If investments drop a lot, trim nice-to-have spending a little; if they grow a lot, allow a little more. Must-haves are never cut." />
          {a.guardrails.enabled && (
            <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="Cut when withdrawals rise by" htmlFor="g-up" help="Compared with the share of savings you withdrew in your first retirement year.">
                <PercentInput id="g-up" value={a.guardrails.upper_band} min={0} max={1} onChange={(v) => set("guardrails", { ...a.guardrails, upper_band: v })} />
              </Field>
              <Field label="Each cut" htmlFor="g-cut"><PercentInput id="g-cut" value={a.guardrails.cut_pct} min={0} max={1} onChange={(v) => set("guardrails", { ...a.guardrails, cut_pct: v })} /></Field>
              <Field label="Raise when withdrawals fall by" htmlFor="g-lo"><PercentInput id="g-lo" value={a.guardrails.lower_band} min={0} max={1} onChange={(v) => set("guardrails", { ...a.guardrails, lower_band: v })} /></Field>
              <Field label="Each raise" htmlFor="g-raise"><PercentInput id="g-raise" value={a.guardrails.raise_pct} min={0} max={1} onChange={(v) => set("guardrails", { ...a.guardrails, raise_pct: v })} /></Field>
              <Field label="Never below (of planned)" htmlFor="g-min"><PercentInput id="g-min" value={a.guardrails.min_multiplier} min={0} max={1} onChange={(v) => set("guardrails", { ...a.guardrails, min_multiplier: v })} /></Field>
              <Field label="Never above (of planned)" htmlFor="g-max"><PercentInput id="g-max" value={a.guardrails.max_multiplier} min={1} max={3} onChange={(v) => set("guardrails", { ...a.guardrails, max_multiplier: v })} /></Field>
            </div>
          )}
        </div>
      </div>

      <button className="mt-4 font-medium text-brand-dark underline" onClick={() => setAdvanced(!advanced)}>{advanced ? "Hide" : "Show"} more assumptions</button>
      {advanced && (
        <div className="mt-4 grid gap-5 md:grid-cols-2">
          <Field label="Social Security yearly increase" htmlFor="cola" help="Leave blank to match inflation (how it normally works).">
            <NumberInput id="cola" allowEmpty suffix="%" value={a.ss_cola === null ? null : Math.round(a.ss_cola * 10000) / 100} onChange={(v) => set("ss_cola", v === null ? null : v / 100)} placeholder="Same as inflation" />
          </Field>
          <div className="flex flex-col gap-3 pt-7">
            <Toggle checked={a.spousal_benefits} onChange={(v) => set("spousal_benefits", v)} label="Include Social Security spousal benefits" />
            <Toggle checked={a.model_medicare_premiums} onChange={(v) => set("model_medicare_premiums", v)} label="Include Medicare premiums from age 65" />
          </div>
          <Field label="Income two years ago and last year" htmlFor="magi" help="Medicare's income surcharge (IRMAA) for the first two plan years looks at income from two years earlier. Use the 'modified adjusted gross income' from those tax returns. Leave blank if unsure.">
            <div className="grid grid-cols-2 gap-2">
              <MoneyInput id="magi" allowEmpty value={a.prior_magi?.[0] ?? null} onChange={(v) => set("prior_magi", v === null ? null : [v, a.prior_magi?.[1] ?? v])} />
              <MoneyInput allowEmpty value={a.prior_magi?.[1] ?? null} onChange={(v) => set("prior_magi", v === null ? null : [a.prior_magi?.[0] ?? v, v])} />
            </div>
          </Field>
          <Field label="Tax rate your heirs would pay" htmlFor="heir" help="Heirs pay income tax when they withdraw inherited pre-tax (401k/IRA) money. Used only to compare strategies by value to heirs.">
            <PercentInput id="heir" value={a.heir_tax_rate} min={0} max={0.5} onChange={(v) => set("heir_tax_rate", v)} />
          </Field>
          <Field label="Tax rules to use" htmlFor="rules">
            <Select id="rules" value={String(a.tax_rule_year ?? "")} onChange={(v) => set("tax_rule_year", v ? Number(v) : null)}
              options={[{ value: "", label: "Latest rules for each year (recommended)" }, ...plan.data.tax_rules.map((r) => ({ value: String(r.tax_year), label: `${r.tax_year} rules only (version ${r.version})` }))]} />
          </Field>
        </div>
      )}

      <ErrorBox error={error} />
      {saved && <Notice tone="good" className="mt-4">Saved. All results now use these assumptions.</Notice>}
      <div className="mt-4 flex flex-wrap gap-2">
        <Button onClick={save} busy={busy}>Save assumptions</Button>
        <Button variant="secondary" onClick={() => setA(structuredClone(plan.data!.assumptions))}>Undo changes</Button>
        <Button variant="ghost" onClick={() => setA({ ...structuredClone(d), state_tax: a.state_tax, roth_conversion: a.roth_conversion, withdrawal_strategy: a.withdrawal_strategy })}>Use standard values</Button>
      </div>

      <details className="mt-5 text-sm">
        <summary className="cursor-pointer font-medium">Tax rule sources and change history</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-muted">
          {plan.data.tax_rules.map((r) => <li key={r.tax_year}><strong>{r.tax_year} (v{r.version}):</strong> {r.sources.join("; ")}</li>)}
        </ul>
        {history.data && (
          <Table className="mt-3" numericFrom={9} head={["Version", "Saved", "Note"]}
            rows={history.data.map((h) => [String(h.version), dateText(h.saved_at), h.note ?? ""])} />
        )}
      </details>
    </Card>
  );
}

function ReturnsCard() {
  const plan = useApi<PlanInfo>("/plan");
  const [rows, setRows] = useState<AssetClassRow[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => { if (plan.data) setRows(plan.data.asset_classes); }, [plan.data]);
  if (!rows) return null;
  async function save() {
    setBusy(true); setError(null); setMsg(null);
    try {
      for (const r of rows!) {
        await api.put(`/plan/asset-classes/${r.key}`, { name: r.name, expected_return: r.expected_return, volatility: r.volatility, income_yield: r.income_yield, qualified_ratio: r.qualified_ratio });
      }
      setMsg("Saved.");
      plan.reload();
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function reset() {
    await api.post("/plan/asset-classes/reset");
    plan.reload();
    setMsg("Reset to the standard values.");
  }
  return (
    <Card title={<>Investment return assumptions<Help text="The average yearly return and how much it bounces around (volatility) for each kind of investment. These are assumptions, not forecasts. Lower numbers make the plan more cautious." /></>}
      subtitle="Before inflation. Change only if you have a reason to.">
      <Table
        numericFrom={1}
        head={["Kind of investment", "Average return / year", "Ups and downs (volatility)", "Paid out as income"]}
        rows={rows.map((r, i) => [
          r.name,
          <div key="e" className="ml-auto w-32"><PercentInput value={r.expected_return} min={-0.2} max={0.3} onChange={(v) => setRows(rows.map((x, j) => (j === i ? { ...x, expected_return: v } : x)))} /></div>,
          <div key="v" className="ml-auto w-32"><PercentInput value={r.volatility} min={0} max={1} onChange={(v) => setRows(rows.map((x, j) => (j === i ? { ...x, volatility: v } : x)))} /></div>,
          <div key="y" className="ml-auto w-32"><PercentInput value={r.income_yield} min={0} max={0.2} onChange={(v) => setRows(rows.map((x, j) => (j === i ? { ...x, income_yield: v } : x)))} /></div>,
        ])}
      />
      <ErrorBox error={error} />
      {msg && <p className="mt-2 text-sm text-good">{msg}</p>}
      <div className="mt-4 flex gap-2">
        <Button onClick={save} busy={busy}>Save</Button>
        <Button variant="secondary" onClick={reset}>Use standard values</Button>
      </div>
    </Card>
  );
}

function SecurityCard() {
  const { user, refresh } = useSession();
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [disableOpen, setDisableOpen] = useState(false);
  const [pw, setPw] = useState({ current: "", next: "" });
  const [error, setError] = useState<unknown>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function attempt(fn: () => Promise<void>) {
    setError(null); setMsg(null);
    try { await fn(); } catch (e) { setError(e); }
  }

  return (
    <Card title="Sign-in security">
      <div className="grid gap-6 md:grid-cols-2">
        <div>
          <h3 className="font-semibold">Two-step verification {user.mfa_enabled ? <Badge tone="good">on</Badge> : <Badge tone="warn">off</Badge>}</h3>
          <p className="mt-1 text-sm text-muted">Asks for a 6-digit code from an app on your phone (such as Google Authenticator or Microsoft Authenticator) when you sign in. Strongly recommended.</p>
          {!user.mfa_enabled && !setup && <Button className="mt-3" onClick={() => attempt(async () => setSetup(await api.post("/auth/mfa/setup")))}>Turn on</Button>}
          {setup && !codes && (
            <div className="mt-3 flex flex-col gap-3 rounded-lg border border-line bg-paper p-4">
              <p className="text-sm">1. In your authenticator app, choose <strong>add account</strong>, then <strong>enter a setup key</strong>, and type this key:</p>
              <p className="break-all rounded bg-white p-2 text-center font-mono text-lg tracking-wider">{setup.secret.match(/.{1,4}/g)?.join(" ")}</p>
              <p className="text-sm">2. Type the 6-digit code the app shows:</p>
              <div className="flex gap-2">
                <TextInput inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} aria-label="Code" className="max-w-40 text-center tracking-widest" />
                <Button onClick={() => attempt(async () => { const r = await api.post<{ recovery_codes: string[] }>("/auth/mfa/enable", { code }); setCodes(r.recovery_codes); await refresh(); })}>Confirm</Button>
              </div>
            </div>
          )}
          {codes && (
            <Notice tone="warn" className="mt-3" title="Save these recovery codes">
              <p>If you lose your phone, each of these codes lets you sign in once. Print them or write them down and keep them somewhere safe.</p>
              <ul className="mt-2 grid grid-cols-2 gap-1 font-mono">{codes.map((c) => <li key={c}>{c}</li>)}</ul>
              <Button variant="secondary" className="mt-3" onClick={() => { setCodes(null); setSetup(null); }}>I have saved them</Button>
            </Notice>
          )}
          {user.mfa_enabled && !codes && <Button variant="danger" className="mt-3" onClick={() => setDisableOpen(true)}>Turn off</Button>}
        </div>
        <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); attempt(async () => { await api.post("/auth/password", { current_password: pw.current, new_password: pw.next }); setPw({ current: "", next: "" }); setMsg("Password changed. Other devices have been signed out."); }); }}>
          <h3 className="font-semibold">Change password</h3>
          <Field label="Current password" htmlFor="pw1"><TextInput id="pw1" type="password" autoComplete="current-password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} required /></Field>
          <Field label="New password" htmlFor="pw2" hint="At least 10 characters"><TextInput id="pw2" type="password" autoComplete="new-password" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} required /></Field>
          <div><Button type="submit" variant="secondary">Change password</Button></div>
        </form>
      </div>
      <ErrorBox error={error} />
      {msg && <Notice tone="good" className="mt-3">{msg}</Notice>}
      <DisableMfa open={disableOpen} onClose={() => setDisableOpen(false)} onDone={async () => { setDisableOpen(false); await refresh(); }} />
    </Card>
  );
}

function DisableMfa({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<unknown>(null);
  return (
    <Modal open={open} onClose={onClose} title="Turn off two-step verification">
      <form className="flex flex-col gap-3" onSubmit={async (e) => { e.preventDefault(); try { await api.post("/auth/mfa/disable", { password, code }); onDone(); } catch (err) { setError(err); } }}>
        <Field label="Password" htmlFor="dm-p"><TextInput id="dm-p" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required /></Field>
        <Field label="Code from your app" htmlFor="dm-c"><TextInput id="dm-c" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} required /></Field>
        <ErrorBox error={error} />
        <div><Button type="submit" variant="danger">Turn off</Button></div>
      </form>
    </Modal>
  );
}

function DataCard() {
  const { household, refresh, signOut, user } = useSession();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  async function act(label: string, fn: () => Promise<void>) {
    setBusy(label); setError(null);
    try { await fn(); } catch (e) { setError(e); } finally { setBusy(null); }
  }

  return (
    <Card title="Your data" subtitle="Your information is stored only for this app. It is never sold or shared.">
      <div id="data" className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-line p-4">
          <h3 className="font-semibold">AI assistant</h3>
          <p className="mt-1 text-sm text-muted">
            {user.ai_consent ? "You have allowed plan summaries to be sent to the external AI service (when one is set up)." : "No plan data is sent to any outside AI service. The built-in helper works privately."}
          </p>
          {user.ai_consent && <Button variant="secondary" className="mt-3" onClick={() => act("ai", async () => { await api.post("/assistant/consent", { consent: false }); await refresh(); })}>Withdraw permission</Button>}
        </div>
        <div className="rounded-lg border border-line p-4">
          <h3 className="font-semibold">Download everything</h3>
          <p className="mt-1 text-sm text-muted">A complete copy of everything stored about you and your household, in one file (JSON).</p>
          <Button variant="secondary" className="mt-3" busy={busy === "export"} onClick={() => act("export", async () => {
            const data = await api.get("/privacy/export");
            saveBlob(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }), `my-data-${new Date().toISOString().slice(0, 10)}.json`);
          })}>Download my data</Button>
        </div>
        <div className="rounded-lg border border-line p-4">
          <h3 className="font-semibold">{household.is_demo ? "Sample data" : "Start over"}</h3>
          <p className="mt-1 text-sm text-muted">{household.is_demo ? "You are using made-up sample data. Clear it to enter your own." : "Remove all people, accounts, income and spending from this plan. Your login stays."}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant={household.is_demo ? "primary" : "danger"} busy={busy === "clear"} onClick={() => {
              if (!window.confirm("Remove all the information in this plan? This cannot be undone.")) return;
              act("clear", async () => { await api.del("/sample-data"); await refresh(); window.location.href = "/setup"; });
            }}>{household.is_demo ? "Clear sample data" : "Clear my plan"}</Button>
            {!household.is_demo && (
              <Button variant="secondary" busy={busy === "sample"} onClick={() => {
                if (!window.confirm("This replaces everything in your plan with made-up sample data. Continue?")) return;
                act("sample", async () => { await api.post("/sample-data"); await refresh(); window.location.href = "/"; });
              }}>Load sample data</Button>
            )}
          </div>
        </div>
        <div className="rounded-lg border border-bad/30 p-4">
          <h3 className="font-semibold text-bad">Delete my account</h3>
          <p className="mt-1 text-sm text-muted">Permanently deletes your login and everything in it. This cannot be undone.</p>
          <Button variant="danger" className="mt-3" onClick={() => setDeleteOpen(true)}>Delete account</Button>
        </div>
      </div>
      <ErrorBox error={error} />
      <Modal open={deleteOpen} onClose={() => setDeleteOpen(false)} title="Delete your account">
        <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); act("delete", async () => { await api.post("/privacy/delete-account", { password, confirm }); await signOut(); }); }}>
          <p>Everything will be deleted permanently. You may want to download your data first.</p>
          <Field label="Your password" htmlFor="del-p"><TextInput id="del-p" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required /></Field>
          <Field label='Type DELETE to confirm' htmlFor="del-c"><TextInput id="del-c" value={confirm} onChange={(e) => setConfirm(e.target.value)} required /></Field>
          <ErrorBox error={error} />
          <div><Button type="submit" variant="danger" disabled={confirm !== "DELETE"} busy={busy === "delete"}>Delete everything</Button></div>
        </form>
      </Modal>
    </Card>
  );
}

const ACTION_LABEL: Record<string, string> = {
  "auth.register": "Account created", "auth.login": "Signed in", "auth.logout": "Signed out", "auth.login_failed": "Wrong password entered",
  "auth.mfa_enabled": "Two-step verification turned on", "auth.mfa_disabled": "Two-step verification turned off", "auth.password_changed": "Password changed",
  "projection.run": "Plan calculated", "monte_carlo.run": "Chance of success calculated", "assumptions.update": "Assumptions changed",
  "sample_data.load": "Sample data loaded", "household.clear": "Plan cleared", "report.create": "Report created", "report.download": "Report downloaded",
  "roth.optimize": "Roth options compared", "roth.apply": "Roth strategy saved", "stress.run": "Bad-market test run", "ai.chat": "Question asked",
  "ai.consent_given": "AI permission given", "ai.consent_withdrawn": "AI permission withdrawn", "privacy.export": "Data downloaded", "import.csv": "File imported",
};

function ActivityCard() {
  const log = useApi<{ at: string; action: string; entity: string | null; detail: Record<string, unknown> | null; by_you: boolean }[]>("/audit?limit=100");
  return (
    <Card title="Activity log" subtitle="A record of sign-ins and changes, for your peace of mind.">
      <details>
        <summary className="cursor-pointer font-medium">Show recent activity</summary>
        {log.data && (
          <Table className="mt-3" numericFrom={9} head={["When", "What happened"]}
            rows={log.data.map((l) => [new Date(l.at).toLocaleString(), ACTION_LABEL[l.action] ?? l.action.replace(/[._]/g, " ")])} />
        )}
      </details>
    </Card>
  );
}
