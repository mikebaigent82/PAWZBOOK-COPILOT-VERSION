"use client";

import { useEffect, useRef, useState } from "react";
import { Badge, Button, Card, cx, ErrorBox, Notice, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";

interface Status {
  mode: "live" | "demo";
  provider_configured: boolean;
  consent_given: boolean;
  consent_required_for_live: boolean;
  consent_text: string;
  model: string | null;
  suggestions: string[];
  demo_note: string;
}

interface Proposal { id: string; title: string; explanation: string; change: Record<string, unknown>; status: string }
interface ChatReply {
  conversation_id: string;
  mode: string;
  notice: string | null;
  reply: string;
  tools_used: { name: string; arguments: Record<string, unknown> }[];
  proposals: Proposal[];
}
interface Msg { role: "user" | "assistant"; content: string; tools?: ChatReply["tools_used"]; mode?: string }

const TOOL_LABEL: Record<string, string> = {
  get_plan_overview: "Checked your plan",
  run_what_if: "Tested a what-if",
  yearly_details: "Looked up a year",
  roth_analysis: "Compared Roth conversions",
  stress_test: "Ran a bad-market test",
  explain_term: "Looked up a term",
  propose_change: "Suggested a change",
};

/** Very small markdown: **bold**, line breaks and "- " bullet lists. */
function Rich({ text }: { text: string }) {
  const blocks = text.split(/\n{2,}/);
  const inline = (s: string) => s.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : <span key={i}>{part}</span>);
  return (
    <>
      {blocks.map((b, i) => {
        const lines = b.split("\n");
        if (lines.every((l) => l.trim().startsWith("- "))) {
          return <ul key={i} className="my-2 list-disc space-y-1 pl-5">{lines.map((l, j) => <li key={j}>{inline(l.trim().slice(2))}</li>)}</ul>;
        }
        return <p key={i} className="my-2">{lines.map((l, j) => <span key={j}>{inline(l)}{j < lines.length - 1 && <br />}</span>)}</p>;
      })}
    </>
  );
}

export default function Assistant() {
  const status = useApi<Status>("/assistant/status");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Block body: newer browsers return a Promise here, which React must not treat as a cleanup.
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  async function send(text: string) {
    const q = text.trim();
    if (!q || busy) return;
    setMessages((m) => [...m, { role: "user", content: q }]);
    setInput("");
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<ChatReply>("/assistant/chat", { message: q, conversation_id: conversationId });
      setConversationId(r.conversation_id);
      setMessages((m) => [...m, { role: "assistant", content: r.reply, tools: r.tools_used, mode: r.mode }]);
      setNotice(r.notice);
      setProposals(r.proposals);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  async function consent(value: boolean) {
    await api.post("/assistant/consent", { consent: value });
    status.reload();
  }

  async function decide(p: Proposal, decision: "apply" | "reject") {
    try {
      await api.post(`/assistant/proposals/${p.id}`, { decision });
      setProposals((list) => list.filter((x) => x.id !== p.id));
      setMessages((m) => [...m, { role: "assistant", content: decision === "apply" ? `Done: **${p.title}** has been saved to your plan.` : `OK, I did not change anything.` }]);
    } catch (e) {
      setError(e);
    }
  }

  const st = status.data;

  return (
    <>
      <PageHeader
        title="Ask a question"
        intro="Ask about your plan in everyday words. Every number in an answer comes from the same calculations as the rest of the app, and nothing in your plan changes unless you confirm it."
        actions={messages.length > 0 && <Button variant="secondary" onClick={() => { setMessages([]); setConversationId(null); setProposals([]); }}>New conversation</Button>}
      />

      {st && (
        <div className="mb-4">
          {st.mode === "demo" && !st.consent_required_for_live && <Notice tone="info">{st.demo_note}</Notice>}
          {st.consent_required_for_live && (
            <Notice tone="warn" title="Turn on the full AI assistant?">
              <p>{st.consent_text}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button onClick={() => consent(true)}>Yes, I agree</Button>
                <span className="self-center text-sm">Until then, the built-in helper answers privately.</span>
              </div>
            </Notice>
          )}
          {st.mode === "live" && (
            <p className="text-sm text-muted">
              <Badge tone="brand">AI assistant on</Badge> Using {st.model}.{" "}
              <button className="underline" onClick={() => consent(false)}>Turn off and keep everything private</button>
            </p>
          )}
        </div>
      )}

      <Card className="flex min-h-[28rem] flex-col">
        <div className="flex-1 space-y-4" aria-live="polite">
          {messages.length === 0 && (
            <div>
              <p className="mb-3 text-muted">Try one of these:</p>
              <div className="flex flex-wrap gap-2">
                {st?.suggestions.map((s) => (
                  <button key={s} onClick={() => send(s)} className="min-h-11 rounded-full border border-line bg-paper px-4 text-left hover:border-brand hover:bg-brand-soft">
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={cx("flex", m.role === "user" ? "justify-end" : "justify-start")}>
              <div className={cx("max-w-[85%] rounded-2xl px-4 py-2", m.role === "user" ? "bg-brand text-white" : "border border-line bg-paper")}>
                {m.role === "assistant" ? <Rich text={m.content} /> : <p className="my-1">{m.content}</p>}
                {m.tools && m.tools.length > 0 && (
                  <p className="mb-1 mt-2 flex flex-wrap gap-1 text-xs text-muted">
                    {m.tools.map((t, j) => <Badge key={j}>{TOOL_LABEL[t.name] ?? t.name}</Badge>)}
                  </p>
                )}
              </div>
            </div>
          ))}
          {busy && <p className="text-muted">Working it out...</p>}
          {proposals.map((p) => (
            <Notice key={p.id} tone="warn" title={`Suggested change: ${p.title}`}>
              {p.explanation && <p>{p.explanation}</p>}
              <p className="mt-1 text-sm">This has not been changed yet. Do you want to save it to your plan?</p>
              <div className="mt-2 flex gap-2">
                <Button onClick={() => decide(p, "apply")}>Confirm</Button>
                <Button variant="secondary" onClick={() => decide(p, "reject")}>No thanks</Button>
              </div>
            </Notice>
          ))}
          <div ref={endRef} />
        </div>
        {notice && <Notice tone="info" className="mt-3">{notice}</Notice>}
        <ErrorBox error={error} />
        <form onSubmit={(e) => { e.preventDefault(); send(input); }} className="mt-4 flex gap-2 border-t border-line pt-4">
          <label htmlFor="q" className="sr-only">Your question</label>
          <input id="q" value={input} onChange={(e) => setInput(e.target.value)} placeholder="Type your question..." maxLength={2000}
            className="min-h-11 flex-1 rounded-lg border border-line px-3 focus:border-brand focus:outline-none" />
          <Button type="submit" busy={busy} disabled={!input.trim()}>Ask</Button>
        </form>
      </Card>
      <p className="mt-3 text-xs text-muted">Answers are estimates from your plan and assumptions, not financial, tax or legal advice.</p>
    </>
  );
}
