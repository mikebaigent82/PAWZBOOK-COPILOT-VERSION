"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, ApiError } from "@/lib/api";
import type { Household, User } from "@/lib/types";
import { Button, ErrorBox, Field, Notice, TextInput } from "./ui";

interface SessionValue {
  user: User;
  household: Household;
  refresh: () => Promise<void>;
  setUser: (u: User) => void;
  signOut: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

export function useSession(): SessionValue {
  const v = useContext(SessionContext);
  if (!v) throw new Error("useSession must be used inside SessionProvider");
  return v;
}

type State =
  | { kind: "loading" }
  | { kind: "signed_out" }
  | { kind: "mfa" }
  | { kind: "ready"; user: User; household: Household }
  | { kind: "error"; message: string };

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ kind: "loading" });

  const refresh = useCallback(async () => {
    try {
      const user = await api.get<User>("/auth/me");
      const household = await api.get<Household>("/household");
      setState({ kind: "ready", user, household });
    } catch (e) {
      if (e instanceof ApiError && e.mfaRequired) setState({ kind: "mfa" });
      else if (e instanceof ApiError && e.status === 401) setState({ kind: "signed_out" });
      else setState({ kind: "error", message: e instanceof Error ? e.message : "Something went wrong." });
    }
  }, []);

  useEffect(() => {
    refresh();
    const onOut = () => setState((s) => (s.kind === "ready" ? { kind: "signed_out" } : s));
    window.addEventListener("tg:signed-out", onOut);
    return () => window.removeEventListener("tg:signed-out", onOut);
  }, [refresh]);

  if (state.kind === "loading") {
    return <div className="flex min-h-screen items-center justify-center text-muted">Loading...</div>;
  }
  if (state.kind === "error") {
    return (
      <AuthFrame>
        <Notice tone="bad" title="We could not load the app">{state.message}</Notice>
        <Button className="mt-4" onClick={refresh}>Try again</Button>
      </AuthFrame>
    );
  }
  if (state.kind === "signed_out") return <SignIn onDone={refresh} />;
  if (state.kind === "mfa") return <MfaPrompt onDone={refresh} onCancel={() => setState({ kind: "signed_out" })} />;

  const value: SessionValue = {
    user: state.user,
    household: state.household,
    refresh,
    setUser: (u) => setState({ ...state, user: u }),
    signOut: async () => {
      try {
        await api.post("/auth/logout");
      } finally {
        setState({ kind: "signed_out" });
      }
    },
  };
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

function AuthFrame({ children }: { children: ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="mb-6 text-center">
          <Logo large />
          <p className="mt-2 text-muted">A clear, private way to plan your retirement.</p>
        </div>
        <div className="rounded-xl border border-line bg-card p-6 shadow-sm">{children}</div>
        <p className="mt-4 text-center text-xs text-muted">
          Estimates only. Not financial, tax or legal advice.
        </p>
      </div>
    </main>
  );
}

export function Logo({ large }: { large?: boolean }) {
  return (
    <span className={`inline-flex items-center gap-2 font-semibold text-brand-dark ${large ? "text-2xl" : "text-lg"}`}>
      <svg width={large ? 34 : 26} height={large ? 34 : 26} viewBox="0 0 32 32" aria-hidden>
        <rect width="32" height="32" rx="8" fill="#1b6b58" />
        <path d="M7 23 C11 15, 14 19, 17 12 S 23 9, 25 7" stroke="#fff" strokeWidth="2.6" fill="none" strokeLinecap="round" />
        <path d="M7 25 H25" stroke="#9fd4c2" strokeWidth="2" strokeLinecap="round" />
      </svg>
      Tallgrass Planner
    </span>
  );
}

function SignIn({ onDone }: { onDone: () => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await api.post("/auth/login", { email, password });
      else await api.post("/auth/register", { email, password, display_name: name });
      onDone();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthFrame>
      <h1 className="text-xl font-semibold">{mode === "login" ? "Sign in" : "Create your account"}</h1>
      <form onSubmit={submit} className="mt-4 flex flex-col gap-4">
        {mode === "register" && (
          <Field label="Your first name" htmlFor="name">
            <TextInput id="name" autoComplete="given-name" value={name} onChange={(e) => setName(e.target.value)} required />
          </Field>
        )}
        <Field label="Email" htmlFor="email">
          <TextInput id="email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </Field>
        <Field label="Password" htmlFor="password" hint={mode === "register" ? "At least 10 characters. A short sentence works well." : undefined}>
          <TextInput id="password" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"}
            value={password} onChange={(e) => setPassword(e.target.value)} required />
        </Field>
        <ErrorBox error={error} />
        <Button type="submit" busy={busy}>{mode === "login" ? "Sign in" : "Create account"}</Button>
      </form>
      <p className="mt-4 text-center text-sm text-muted">
        {mode === "login" ? "New here? " : "Already have an account? "}
        <button type="button" className="font-medium text-brand-dark underline" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(null); }}>
          {mode === "login" ? "Create an account" : "Sign in"}
        </button>
      </p>
    </AuthFrame>
  );
}

function MfaPrompt({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/auth/mfa/verify", { code });
      onDone();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return (
    <AuthFrame>
      <h1 className="text-xl font-semibold">Enter your 6-digit code</h1>
      <p className="mt-1 text-muted">Open your authenticator app and type the code shown for Tallgrass Planner. You can also use one of your recovery codes.</p>
      <form onSubmit={submit} className="mt-4 flex flex-col gap-4">
        <TextInput aria-label="Code" inputMode="numeric" autoComplete="one-time-code" value={code}
          onChange={(e) => setCode(e.target.value)} className="text-center text-2xl tracking-widest" autoFocus required />
        <ErrorBox error={error} />
        <Button type="submit" busy={busy}>Continue</Button>
        <Button type="button" variant="ghost" onClick={async () => { await api.post("/auth/logout").catch(() => {}); onCancel(); }}>
          Use a different account
        </Button>
      </form>
    </AuthFrame>
  );
}
