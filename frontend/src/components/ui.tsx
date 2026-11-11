"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

export function PageHeader({ title, intro, actions }: { title: string; intro?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="max-w-3xl">
        <h1 className="text-[1.75rem] font-semibold leading-tight text-ink">{title}</h1>
        {intro && <p className="mt-2 text-muted">{intro}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2 no-print">{actions}</div>}
    </header>
  );
}

export function Card({ title, children, className, actions, subtitle }: {
  title?: ReactNode; subtitle?: ReactNode; children: ReactNode; className?: string; actions?: ReactNode;
}) {
  return (
    <section className={cx("rounded-xl border border-line bg-card p-5 shadow-sm", className)}>
      {(title || actions) && (
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            {title && <h2 className="text-lg font-semibold text-ink">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
          </div>
          {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  busy?: boolean;
};

export function Button({ variant = "primary", busy, className, children, disabled, ...rest }: ButtonProps) {
  const styles = {
    primary: "bg-brand text-white hover:bg-brand-dark border border-brand",
    secondary: "bg-white text-ink border border-line hover:border-brand hover:text-brand-dark",
    ghost: "bg-transparent text-brand-dark border border-transparent hover:bg-brand-soft",
    danger: "bg-white text-bad border border-bad/40 hover:bg-bad-soft",
  }[variant];
  return (
    <button
      {...rest}
      disabled={disabled || busy}
      className={cx(
        "inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 py-2 font-medium transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-60",
        styles,
        className,
      )}
    >
      {busy && <Spinner />}
      {children}
    </button>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span role="status" className="inline-flex items-center gap-2">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden />
      {label ? <span>{label}</span> : <span className="sr-only">Working</span>}
    </span>
  );
}

export function Loading({ label = "Loading..." }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-line bg-card p-6 text-muted">
      <Spinner label={label} />
    </div>
  );
}

export function Notice({ tone = "info", title, children, className }: {
  tone?: "info" | "good" | "warn" | "bad"; title?: ReactNode; children?: ReactNode; className?: string;
}) {
  const styles = {
    info: "bg-info-soft border-[#c6d4ea]",
    good: "bg-good-soft border-[#b9dfc7]",
    warn: "bg-warn-soft border-[#efd59c]",
    bad: "bg-bad-soft border-[#efbdb6]",
  }[tone];
  return (
    <div role={tone === "bad" ? "alert" : undefined} className={cx("rounded-lg border p-4", styles, className)}>
      {title && <p className="font-semibold">{title}</p>}
      {children && <div className={cx(!!title && "mt-1", "text-[0.95rem]")}>{children}</div>}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  return <Notice tone="bad">{message}</Notice>;
}

/** A small "?" that explains a term in plain English. */
export function Help({ text, label = "What does this mean?" }: { text: ReactNode; label?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  return (
    <span ref={ref} className="relative inline-block align-middle">
      <button
        type="button"
        aria-label={label}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((v) => !v)}
        className="ml-1 inline-flex h-6 w-6 items-center justify-center rounded-full border border-brand/40 bg-brand-soft text-xs font-bold text-brand-dark hover:bg-brand hover:text-white"
      >
        ?
      </button>
      {open && (
        <span
          id={id}
          role="tooltip"
          className="absolute left-1/2 z-30 mt-2 block w-72 -translate-x-1/2 rounded-lg border border-line bg-white p-3 text-left text-sm font-normal leading-snug text-ink shadow-lg"
        >
          {text}
        </span>
      )}
    </span>
  );
}

export function Field({ label, help, hint, children, error, htmlFor }: {
  label: ReactNode; help?: ReactNode; hint?: ReactNode; children: ReactNode; error?: string; htmlFor?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={htmlFor} className="font-medium text-ink">
        {label}
        {help && <Help text={help} />}
      </label>
      {children}
      {hint && <p className="text-sm text-muted">{hint}</p>}
      {error && <p className="text-sm text-bad">{error}</p>}
    </div>
  );
}

const inputCls =
  "min-h-11 w-full rounded-lg border border-line bg-white px-3 py-2 text-ink placeholder:text-[#9aa5a0] focus:border-brand focus:outline-none";

export function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(inputCls, props.className)} />;
}

export function Select({ options, value, onChange, id, className, disabled }: {
  options: { value: string; label: string }[]; value: string; onChange: (v: string) => void; id?: string;
  className?: string; disabled?: boolean;
}) {
  return (
    <select id={id} value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}
      className={cx(inputCls, "pr-8", className)}>
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}

/** Number input that keeps its own text so typing "1,5" or a blank field never jumps around. */
export function NumberInput({ value, onChange, id, min, max, step, prefix, suffix, placeholder, allowEmpty }: {
  value: number | null; onChange: (v: number | null) => void; id?: string; min?: number; max?: number;
  step?: number; prefix?: string; suffix?: string; placeholder?: string; allowEmpty?: boolean;
}) {
  const fmt = (v: number | null) => (v === null || v === undefined ? "" : String(v));
  const [text, setText] = useState(fmt(value));
  const last = useRef(value);
  useEffect(() => {
    if (value !== last.current) {
      setText(fmt(value));
      last.current = value;
    }
  }, [value]);
  return (
    <div className="flex items-stretch">
      {prefix && (
        <span className="flex items-center rounded-l-lg border border-r-0 border-line bg-paper px-3 text-muted">
          {prefix}
        </span>
      )}
      <input
        id={id}
        inputMode="decimal"
        className={cx(inputCls, prefix && "rounded-l-none", suffix && "rounded-r-none")}
        value={text}
        placeholder={placeholder}
        onChange={(e) => {
          const raw = e.target.value.replace(/[^0-9.\-]/g, "");
          setText(e.target.value);
          if (raw === "" || raw === "-" || raw === ".") {
            if (allowEmpty) {
              last.current = null;
              onChange(null);
            }
            return;
          }
          let n = Number(raw);
          if (Number.isNaN(n)) return;
          if (step && step >= 1) n = Math.round(n);
          last.current = n;
          onChange(n);
        }}
        onBlur={() => {
          let n = value;
          if (n !== null && min !== undefined && n < min) n = min;
          if (n !== null && max !== undefined && n > max) n = max;
          if (n !== value) {
            last.current = n;
            onChange(n);
          }
          setText(n === null ? "" : prefix === "$" ? n.toLocaleString("en-US") : String(n));
        }}
        onFocus={() => setText(fmt(value))}
      />
      {suffix && (
        <span className="flex items-center rounded-r-lg border border-l-0 border-line bg-paper px-3 text-muted">
          {suffix}
        </span>
      )}
    </div>
  );
}

export function MoneyInput(props: { value: number | null; onChange: (v: number | null) => void; id?: string; allowEmpty?: boolean; placeholder?: string }) {
  return <NumberInput {...props} prefix="$" min={0} />;
}

/** Percent input: shows 4 for 0.04. */
export function PercentInput({ value, onChange, id, min, max }: {
  value: number; onChange: (v: number) => void; id?: string; min?: number; max?: number;
}) {
  return (
    <NumberInput
      id={id}
      value={Math.round(value * 10000) / 100}
      onChange={(v) => onChange((v ?? 0) / 100)}
      suffix="%"
      min={min !== undefined ? min * 100 : undefined}
      max={max !== undefined ? max * 100 : undefined}
    />
  );
}

export function Toggle({ checked, onChange, label, id, description }: {
  checked: boolean; onChange: (v: boolean) => void; label: ReactNode; id?: string; description?: ReactNode;
}) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <div className="flex items-start gap-3">
      <button
        id={fid}
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cx(
          "relative mt-0.5 h-7 w-12 shrink-0 rounded-full border transition-colors",
          checked ? "border-brand bg-brand" : "border-line bg-[#e4e6e0]",
        )}
      >
        <span className={cx("absolute top-0.5 h-5.5 w-5.5 rounded-full bg-white shadow transition-all",
          checked ? "left-[1.4rem]" : "left-0.5")} />
      </button>
      <label htmlFor={fid} className="cursor-pointer">
        <span className="font-medium">{label}</span>
        {description && <span className="block text-sm text-muted">{description}</span>}
      </label>
    </div>
  );
}

export function Segmented<T extends string>({ value, onChange, options, label }: {
  value: T; onChange: (v: T) => void; options: { value: T; label: string }[]; label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg border border-line bg-white p-1">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cx(
            "min-h-9 rounded-md px-3 text-sm font-medium",
            value === o.value ? "bg-brand text-white" : "text-muted hover:text-ink",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Stat({ label, value, sub, help, tone }: {
  label: ReactNode; value: ReactNode; sub?: ReactNode; help?: ReactNode; tone?: "good" | "warn" | "bad";
}) {
  const color = tone === "good" ? "text-good" : tone === "warn" ? "text-warn" : tone === "bad" ? "text-bad" : "text-ink";
  return (
    <div className="rounded-xl border border-line bg-card p-4">
      <p className="text-sm text-muted">
        {label}
        {help && <Help text={help} />}
      </p>
      <p className={cx("mt-1 text-2xl font-semibold tabular-nums", color)}>{value}</p>
      {sub && <p className="mt-0.5 text-sm text-muted">{sub}</p>}
    </div>
  );
}

export function Badge({ tone = "neutral", children }: { tone?: "neutral" | "good" | "warn" | "bad" | "brand"; children: ReactNode }) {
  const styles = {
    neutral: "bg-[#eef0eb] text-muted",
    good: "bg-good-soft text-good",
    warn: "bg-warn-soft text-warn",
    bad: "bg-bad-soft text-bad",
    brand: "bg-brand-soft text-brand-dark",
  }[tone];
  return <span className={cx("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold", styles)}>{children}</span>;
}

export function Modal({ open, onClose, title, children, wide }: {
  open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      className={cx(
        "m-auto w-[calc(100%-2rem)] rounded-xl border border-line bg-white p-0 text-ink shadow-xl backdrop:bg-black/40",
        wide ? "max-w-3xl" : "max-w-xl",
      )}
    >
      {open && (
        <div className="max-h-[85vh] overflow-y-auto p-6">
          <div className="mb-4 flex items-start justify-between gap-4">
            <h2 className="text-xl font-semibold">{title}</h2>
            <button type="button" onClick={onClose} aria-label="Close" className="rounded-md px-2 text-2xl leading-none text-muted hover:text-ink">
              ×
            </button>
          </div>
          {children}
        </div>
      )}
    </dialog>
  );
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line bg-white/60 p-8 text-center">
      <p className="text-lg font-semibold">{title}</p>
      {children && <div className="mx-auto mt-1 max-w-lg text-muted">{children}</div>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

export function Table({ head, rows, className, numericFrom = 1, caption }: {
  head: ReactNode[]; rows: ReactNode[][]; className?: string; numericFrom?: number; caption?: string;
}) {
  return (
    <div className={cx("overflow-x-auto rounded-lg border border-line", className)}>
      <table className="w-full border-collapse text-sm">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead className="bg-paper text-left">
          <tr>
            {head.map((h, i) => (
              <th key={i} scope="col" className={cx("whitespace-nowrap px-3 py-2 font-semibold text-muted", i >= numericFrom && "text-right")}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, ri) => (
            <tr key={ri} className="border-t border-line odd:bg-white even:bg-[#fafaf7]">
              {r.map((c, ci) => (
                <td key={ci} className={cx("px-3 py-2", ci >= numericFrom && "text-right tabular-nums")}>{c}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Disclaimer({ className }: { className?: string }) {
  return (
    <p className={cx("text-xs leading-relaxed text-muted", className)}>
      These are estimates based on the information and assumptions entered. They are not guarantees, and not
      financial, tax, investment or legal advice.
    </p>
  );
}

export function AssumptionLine({ children }: { children: ReactNode }) {
  return <p className="mt-3 border-t border-line pt-2 text-xs leading-relaxed text-muted">{children}</p>;
}
