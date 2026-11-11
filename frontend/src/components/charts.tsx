"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { money, pct } from "@/lib/format";

const axisMoney = (v: number) => money(v, { compact: true });
const tick = { fill: "#55635e", fontSize: 13 };

function TipBox({ title, items }: { title: string; items: { label: string; value: string; color?: string }[] }) {
  return (
    <div className="rounded-lg border border-line bg-white p-3 text-sm shadow-md">
      <p className="mb-1 font-semibold">{title}</p>
      {items.map((it) => (
        <p key={it.label} className="flex justify-between gap-6">
          <span className="flex items-center gap-2">
            {it.color && <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: it.color }} />}
            {it.label}
          </span>
          <span className="font-medium tabular-nums">{it.value}</span>
        </p>
      ))}
    </div>
  );
}

/** Range of outcomes from the simulation plus the average-return line. */
export function FanChart({ years, ages, p10, p50, p90, projection, retireYear, height = 320 }: {
  years: number[]; ages?: (number | null)[]; p10: number[]; p50: number[]; p90: number[]; projection?: number[];
  retireYear?: number; height?: number;
}) {
  const data = years.map((y, i) => ({
    year: y,
    age: ages?.[i] ?? null,
    band: [p10[i], p90[i]] as [number, number],
    p10: p10[i],
    p50: p50[i],
    p90: p90[i],
    projection: projection?.[i],
  }));
  return (
    <div role="img" aria-label="Chart of how much money you may have each year, showing a range from poor to strong markets.">
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={{ top: 10, right: 12, left: 4, bottom: 0 }}>
          <CartesianGrid stroke="#e7e8e2" vertical={false} />
          <XAxis dataKey="year" tick={tick} minTickGap={24} />
          <YAxis tickFormatter={axisMoney} tick={tick} width={64} />
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const d = payload[0].payload as (typeof data)[number];
              return (
                <TipBox
                  title={`${d.year}${d.age ? ` (age ${d.age})` : ""}`}
                  items={[
                    { label: "Strong markets", value: money(d.p90), color: "#9fd4c2" },
                    { label: "Middle outcome", value: money(d.p50), color: "#1b6b58" },
                    { label: "Poor markets", value: money(d.p10), color: "#9fd4c2" },
                    ...(d.projection !== undefined ? [{ label: "Average returns", value: money(d.projection), color: "#c98f1f" }] : []),
                  ]}
                />
              );
            }}
          />
          <Area dataKey="band" stroke="none" fill="#bfe3d6" fillOpacity={0.8} name="Range (poor to strong markets)" isAnimationActive={false} />
          <Line dataKey="p50" stroke="#1b6b58" strokeWidth={3} dot={false} name="Middle outcome" isAnimationActive={false} />
          {projection && (
            <Line dataKey="projection" stroke="#c98f1f" strokeWidth={2} strokeDasharray="6 4" dot={false} name="Average returns every year" isAnimationActive={false} />
          )}
          {retireYear && <ReferenceLine x={retireYear} stroke="#55635e" strokeDasharray="3 3" label={{ value: "Retire", fill: "#55635e", fontSize: 12, position: "top" }} />}
          <ReferenceLine y={0} stroke="#b3372c" />
          <Legend wrapperStyle={{ fontSize: 14 }} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Balances stacked by account type. */
export function StackedBalances({ data, keys, height = 300 }: {
  data: Record<string, number>[]; keys: { key: string; label: string; color: string }[]; height?: number;
}) {
  return (
    <div role="img" aria-label="Chart of savings by account type over time.">
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data} margin={{ top: 10, right: 12, left: 4, bottom: 0 }}>
          <CartesianGrid stroke="#e7e8e2" vertical={false} />
          <XAxis dataKey="year" tick={tick} minTickGap={24} />
          <YAxis tickFormatter={axisMoney} tick={tick} width={64} />
          <Tooltip
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              const total = payload.reduce((s, p) => s + Number(p.value ?? 0), 0);
              return (
                <TipBox
                  title={String(label)}
                  items={[
                    ...[...payload].reverse().map((p) => ({ label: String(p.name), value: money(Number(p.value)), color: String(p.color) })),
                    { label: "Total", value: money(total) },
                  ]}
                />
              );
            }}
          />
          {keys.map((k) => (
            <Area key={k.key} type="monotone" dataKey={k.key} name={k.label} stackId="1" stroke={k.color} fill={k.color} fillOpacity={0.75} isAnimationActive={false} />
          ))}
          <Legend wrapperStyle={{ fontSize: 14 }} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Income sources vs spending each year. */
export function CashFlowChart({ data, height = 300 }: { data: Record<string, number>[]; height?: number }) {
  const series = [
    { key: "pay", label: "Pay", color: "#3a7ca5" },
    { key: "ss", label: "Social Security", color: "#1b6b58" },
    { key: "other", label: "Pensions & other", color: "#8f5fa0" },
    { key: "savings", label: "From savings", color: "#c98f1f" },
  ];
  return (
    <div role="img" aria-label="Chart of where each year's money comes from, compared with spending.">
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={{ top: 10, right: 12, left: 4, bottom: 0 }}>
          <CartesianGrid stroke="#e7e8e2" vertical={false} />
          <XAxis dataKey="year" tick={tick} minTickGap={24} />
          <YAxis tickFormatter={axisMoney} tick={tick} width={64} />
          <Tooltip
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              return (
                <TipBox
                  title={String(label)}
                  items={payload.map((p) => ({ label: String(p.name), value: money(Number(p.value)), color: String(p.color) }))}
                />
              );
            }}
          />
          {series.map((s) => (
            <Bar key={s.key} dataKey={s.key} name={s.label} stackId="a" fill={s.color} isAnimationActive={false} />
          ))}
          <Line dataKey="spending" name="Spending + taxes" stroke="#1c2925" strokeWidth={2} dot={false} isAnimationActive={false} />
          <Legend wrapperStyle={{ fontSize: 14 }} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function SimpleLines({ data, lines, height = 280, percent }: {
  data: Record<string, number | string>[]; lines: { key: string; label: string; color: string; dashed?: boolean }[];
  height?: number; percent?: boolean;
}) {
  const fmt = percent ? (v: number) => pct(v) : axisMoney;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 10, right: 12, left: 4, bottom: 0 }}>
        <CartesianGrid stroke="#e7e8e2" vertical={false} />
        <XAxis dataKey="year" tick={tick} minTickGap={24} />
        <YAxis tickFormatter={fmt} tick={tick} width={64} />
        <Tooltip
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null;
            return (
              <TipBox
                title={String(label)}
                items={payload.map((p) => ({ label: String(p.name), value: percent ? pct(Number(p.value)) : money(Number(p.value)), color: String(p.color) }))}
              />
            );
          }}
        />
        {lines.map((l) => (
          <Line key={l.key} dataKey={l.key} name={l.label} stroke={l.color} strokeWidth={2.5} strokeDasharray={l.dashed ? "6 4" : undefined} dot={false} isAnimationActive={false} />
        ))}
        <Legend wrapperStyle={{ fontSize: 14 }} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function Donut({ data, height = 240 }: { data: { name: string; value: number; color: string }[]; height?: number }) {
  const total = data.reduce((s, d) => s + d.value, 0);
  return (
    <div className="flex flex-col items-center gap-4 sm:flex-row">
      <div className="h-[220px] w-[220px] shrink-0" role="img" aria-label="Pie chart of how your money is split.">
        <ResponsiveContainer width="100%" height={height > 220 ? 220 : height}>
          <PieChart>
            <Pie data={data} dataKey="value" nameKey="name" innerRadius="58%" outerRadius="95%" stroke="#fff" isAnimationActive={false}>
              {data.map((d) => (
                <Cell key={d.name} fill={d.color} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
      </div>
      <ul className="w-full space-y-2">
        {data.map((d) => (
          <li key={d.name} className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-2">
              <span className="inline-block h-3 w-3 rounded-sm" style={{ background: d.color }} />
              {d.name}
            </span>
            <span className="tabular-nums text-muted">
              {money(d.value)} <span className="ml-1 font-semibold text-ink">{total ? pct(d.value / total) : "-"}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Histogram({ edges, counts, height = 220 }: { edges: number[]; counts: number[]; height?: number }) {
  const total = counts.reduce((a, b) => a + b, 0) || 1;
  const data = counts.map((c, i) => ({ label: `${money(edges[i], { compact: true })}`, from: edges[i], to: edges[i + 1], share: c / total }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 10, right: 12, left: 4, bottom: 0 }}>
        <CartesianGrid stroke="#e7e8e2" vertical={false} />
        <XAxis dataKey="label" tick={{ ...tick, fontSize: 11 }} interval="preserveStartEnd" />
        <YAxis tickFormatter={(v: number) => pct(v)} tick={tick} width={48} />
        <Tooltip
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const d = payload[0].payload as (typeof data)[number];
            return <TipBox title={`${money(d.from)} to ${money(d.to)}`} items={[{ label: "Share of futures", value: pct(d.share, 1) }]} />;
          }}
        />
        <Bar dataKey="share" fill="#1b6b58" isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  );
}
