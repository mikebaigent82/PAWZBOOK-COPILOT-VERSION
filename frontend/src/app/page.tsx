"use client";

import Link from "next/link";
import { FanChart } from "@/components/charts";
import { useSession } from "@/components/session";
import { AssumptionLine, Badge, Button, Card, cx, Empty, ErrorBox, Help, Loading, PageHeader, Stat } from "@/components/ui";
import { money, pct, signedPoints } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Insights } from "@/lib/types";

interface Levers {
  baseline: number;
  n_paths: number;
  levers: { key: string; label: string; success_probability: number; change: number }[];
  note: string;
}

const STATUS = {
  on_track: { label: "On track", tone: "good" as const, ring: "#1b7a4b", bg: "bg-good-soft" },
  watch: { label: "Worth a look", tone: "warn" as const, ring: "#c98f1f", bg: "bg-warn-soft" },
  at_risk: { label: "Needs attention", tone: "bad" as const, ring: "#b3372c", bg: "bg-bad-soft" },
};

function Gauge({ value, color }: { value: number; color: string }) {
  const r = 52;
  const c = 2 * Math.PI * r;
  return (
    <svg width="140" height="140" viewBox="0 0 140 140" role="img" aria-label={`${pct(value)} chance of success`}>
      <circle cx="70" cy="70" r={r} fill="none" stroke="#e7e8e2" strokeWidth="14" />
      <circle cx="70" cy="70" r={r} fill="none" stroke={color} strokeWidth="14" strokeLinecap="round"
        strokeDasharray={`${c * value} ${c}`} transform="rotate(-90 70 70)" />
      <text x="70" y="70" textAnchor="middle" fontSize="30" fontWeight="700" fill="#1c2925">{pct(value)}</text>
      <text x="70" y="88" textAnchor="middle" fontSize="11" fill="#55635e">chance of</text>
      <text x="70" y="101" textAnchor="middle" fontSize="11" fill="#55635e">success</text>
    </svg>
  );
}

export default function Home() {
  const { user, household } = useSession();
  const ins = useApi<Insights>(household.member_count ? "/insights" : null);
  const levers = useApi<Levers>(household.member_count ? "/insights/levers" : null);

  if (!household.member_count) {
    return (
      <>
        <PageHeader title={`Welcome, ${user.display_name}`} />
        <Empty title="Let's set up your plan" action={<Link href="/setup"><Button>Start setup</Button></Link>}>
          It takes about 10 minutes. You can also explore with made-up sample data first.
        </Empty>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Am I on track?"
        intro="A plain-English check-up of your retirement plan, based on what you have entered."
        actions={<Link href="/assistant"><Button variant="secondary">Ask a question</Button></Link>}
      />
      {ins.loading && !ins.data && <Loading label="Checking your plan in 1,000 possible futures..." />}
      <ErrorBox error={ins.error} />
      {ins.error && <p className="mt-3"><Link className="font-medium text-brand-dark underline" href="/setup">Review your details</Link></p>}

      {ins.data && (() => {
        const d = ins.data;
        const st = STATUS[d.status];
        const p = d.numbers.success_probability ?? 0;
        return (
          <div className="flex flex-col gap-6">
            <section className={cx("rounded-xl border border-line p-6", st.bg)}>
              <div className="flex flex-col items-center gap-6 md:flex-row md:items-start">
                <Gauge value={p} color={st.ring} />
                <div className="flex-1">
                  <Badge tone={st.tone}>{st.label}</Badge>
                  <h2 className="mt-2 text-2xl font-semibold">{d.headline}</h2>
                  <ul className="mt-3 space-y-2">
                    {d.points.map((pt, i) => (
                      <li key={i} className="flex gap-2">
                        <span aria-hidden className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-ink" />
                        <span>{pt.text}</span>
                      </li>
                    ))}
                  </ul>
                  <p className="mt-3 text-sm text-muted">
                    How to read the score
                    <Help text={<>
                      We try your plan in {d.simulation.n_paths.toLocaleString()} made-up futures, some with good markets and some with bad.
                      The score is the share of those futures where your money lasts. {d.thresholds.note}
                    </>} />
                  </p>
                </div>
              </div>
            </section>

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Stat label="Your investments today" value={money(d.numbers.investments_today)} sub="All accounts combined" />
              <Stat label="Plan runs until" value={`Age ${d.numbers.plan_end_age}`} sub={`The year ${d.numbers.plan_end_year}`}
                help="We plan to this age so there is a cushion in case you live longer than average. You can change it on the Income & spending page." />
              <Stat label="Left at the end (average returns)" value={money(d.numbers.ending_portfolio_real)} sub="In today's dollars"
                tone={d.numbers.funded_in_projection ? "good" : "bad"}
                help="If investments earned their average return every single year. Real markets go up and down, which the chance-of-success score accounts for." />
              <Stat label="Lifetime taxes" value={money(d.numbers.lifetime_taxes_real)} sub="In today's dollars"
                help="Federal, state and payroll taxes over the whole plan. See the Taxes page for ways to reduce them." />
            </div>

            <Card
              title="Your savings over time"
              subtitle="In today's dollars, so amounts are easy to compare with what things cost now."
              actions={<Link href="/plan"><Button variant="secondary">See year by year</Button></Link>}
            >
              <FanChart years={d.chart.years} p10={d.chart.p10_real} p50={d.chart.p50_real} p90={d.chart.p90_real} projection={d.chart.projection_real} />
              <p className="mt-2 text-sm text-muted">
                The shaded area shows the range from poor markets (bottom) to strong markets (top). The dark line is a middle outcome.
                The dashed line assumes average returns every year.
              </p>
              <AssumptionLine>
                Simulation: {d.simulation.n_paths.toLocaleString()} futures, seed {d.simulation.seed}, {d.simulation.distribution} returns.
                Inflation {pct(d.meta.inflation_assumption, 1)} a year. Tax rules {d.meta.tax_rule_versions.join(", ")}. Engine {d.meta.engine_version}.
                Input fingerprint {d.meta.plan_hash.slice(0, 12)}.
              </AssumptionLine>
            </Card>

            <Card title="What would make the biggest difference?" subtitle="Each idea was tested the same way, so you can compare them fairly.">
              {levers.loading && <Loading label="Testing a few ideas..." />}
              <ErrorBox error={levers.error} />
              {levers.data && (
                <>
                  <ul className="divide-y divide-line">
                    {levers.data.levers.map((l) => (
                      <li key={l.key} className="flex flex-wrap items-center justify-between gap-3 py-3">
                        <span className="font-medium">{l.label}</span>
                        <span className="flex items-center gap-3">
                          <span className="tabular-nums text-muted">{pct(levers.data!.baseline)} → <strong className="text-ink">{pct(l.success_probability)}</strong></span>
                          <Badge tone={l.change > 0.005 ? "good" : l.change < -0.005 ? "bad" : "neutral"}>{signedPoints(l.change)}</Badge>
                        </span>
                      </li>
                    ))}
                  </ul>
                  <p className="mt-3 text-sm text-muted">{levers.data.note}</p>
                  <Link href="/what-if"><Button variant="secondary" className="mt-3">Try your own what-ifs</Button></Link>
                </>
              )}
            </Card>

            {d.notes.length > 0 && (
              <Card title="Good to know">
                <ul className="list-disc space-y-1 pl-5 text-muted">
                  {d.notes.map((n) => <li key={n}>{n}</li>)}
                </ul>
              </Card>
            )}
          </div>
        );
      })()}
    </>
  );
}
