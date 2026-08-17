import { useEffect, useRef, useState } from "react";
import { sendChat } from "../api";
import type { ChatMessage } from "../types";
import type { Cite } from "./Evidence";
import { Search, Send, Sparkle, Spinner, X } from "./icons";

const SUGGESTIONS = [
  "fetch the evidence for ANS-001",
  "why is Kelvin Ong not claimed?",
  "what is the qualifying salary cap?",
];

/**
 * The assistant emits **bold** around the figures and names it is asserting
 * (edb_claim/llm/qa.py), so render that one markup rather than printing the
 * asterisks. Deliberately not a markdown parser: the answer text is data, and
 * the only thing interpreted here is the emphasis the answer itself sets.
 */
function emphasise(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4 ? (
      <b key={i} className="font-semibold text-ink">{part.slice(2, -2)}</b>
    ) : (
      part
    )
  );
}

/**
 * FR-14 transparency: every answer shows whether its figures were verified
 * against the claim rows, and says plainly why when they were not. Nothing is
 * hidden — an unverified answer is still shown, just marked.
 */
function GroundingBadge({
  grounded,
  confidence,
  reason,
}: {
  grounded: boolean;
  confidence?: number | null;
  reason?: string | null;
}) {
  const pct = confidence == null ? null : `${Math.round(confidence * 100)}%`;
  return (
    <div className="mt-2 border-t border-slate-200/70 pt-2">
      <div className="flex items-center gap-1.5 text-[11px] font-medium">
        <span
          className={
            "inline-flex items-center gap-1 rounded-full px-2 py-0.5 " +
            (grounded
              ? "bg-emerald-50 text-emerald-700"
              : "bg-amber-100 text-amber-800")
          }
        >
          {grounded ? "✓ Figures verified" : "⚠ Unverified figure"}
        </span>
        {pct && <span className="text-slate-400">confidence {pct}</span>}
      </div>
      {reason && (
        <p className="mt-1 text-[11px] leading-snug text-slate-500">{reason}</p>
      )}
    </div>
  );
}

export default function Chat({
  session,
  llmEnabled,
  onCite,
}: {
  session: string;
  llmEnabled: boolean;
  onCite: (c: Cite) => void;
}) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // ⌘K / Ctrl-K toggles the assistant
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 80);
  }, [open]);
  // Block body on purpose — see the note in Analyzing.tsx: a concise arrow returns
  // scrollIntoView()'s value, which React would try to call as effect cleanup.
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  const ask = async (q: string) => {
    const question = q.trim();
    if (!question || sending) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text: question }]);
    setSending(true);
    try {
      const ans = await sendChat(session, question);
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          text: ans.text,
          citations: ans.citations,
          mode: ans.mode,
          grounded: ans.grounded,
          confidence: ans.confidence,
          confidenceReason: ans.confidence_reason,
        },
      ]);
    } catch (e: any) {
      setMessages((m) => [
        ...m,
        { role: "assistant", text: `Sorry — ${String(e?.message || e)}` },
      ]);
    } finally {
      setSending(false);
    }
  };

  return (
    <>
      {/* floating launcher, bottom-right */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed bottom-6 right-6 z-40 flex items-center gap-2 rounded-full bg-ink py-3 pl-4 pr-3 text-sm font-semibold text-white shadow-xl shadow-ink/30 transition-transform hover:scale-105"
        >
          <Sparkle width={17} height={17} /> Ask
          <kbd className="rounded-md bg-white/15 px-1.5 py-0.5 text-[11px] font-medium">⌘K</kbd>
        </button>
      )}

      {/* docked panel */}
      {open && (
        <div className="fixed bottom-6 right-6 z-50 flex h-[560px] max-h-[80vh] w-[400px] max-w-[92vw] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl shadow-ink/25 animate-fade-up">
          {/* header */}
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
            <div className="flex items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-ink text-white">
                <Sparkle width={16} height={16} />
              </span>
              <div className="leading-tight">
                <div className="text-sm font-semibold text-ink">Grant &amp; Verification Assistant</div>
                <div className="text-[11px] text-slate-400">
                  {llmEnabled ? "🟢 Local model connected" : "⚪ Offline — answering from your claim data & scheme rules"}
                </div>
              </div>
            </div>
            <button className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100" onClick={() => setOpen(false)}>
              <X width={17} height={17} />
            </button>
          </div>

          {/* messages */}
          <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
            {messages.length === 0 && (
              <div className="text-[13px] text-slate-500">
                <p className="mb-3">
                  Hi — ask me about the RIS(C) rules, a person's claim or reason, or say
                  “fetch the evidence for &lt;name&gt;” to pull the supporting documents.
                </p>
                <div className="flex flex-col gap-1.5">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() => ask(s)}
                      className="rounded-lg border border-slate-200 px-3 py-2 text-left text-[13px] text-slate-600 hover:border-edb-300 hover:bg-edb-50"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((m, i) => (
              <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
                <div
                  className={
                    "max-w-[86%] rounded-2xl px-3.5 py-2.5 text-[13px] leading-relaxed " +
                    (m.role === "user"
                      ? "bg-ink text-white"
                      : "bg-slate-100 text-slate-700")
                  }
                >
                  <div className="whitespace-pre-wrap">{emphasise(m.text)}</div>
                  {m.role === "assistant" && m.grounded !== undefined && (
                    <GroundingBadge
                      grounded={m.grounded}
                      confidence={m.confidence}
                      reason={m.confidenceReason}
                    />
                  )}
                  {m.citations && m.citations.length > 0 && (
                    <div className="mt-2 space-y-1 border-t border-slate-200/70 pt-2">
                      {m.citations.slice(0, 12).map((c, ci) => (
                        <button
                          key={ci}
                          onClick={() =>
                            onCite({ file: c.file, sheet: c.sheet, cell: c.cell, label: c.label })
                          }
                          className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-left text-[11px] font-medium text-edb-600 hover:bg-edb-50"
                        >
                          <Search width={12} height={12} />
                          <span className="truncate">
                            {(c.label || "source")} — {fileBase(c.file)}
                            {c.cell ? ` · ${c.cell}` : ""}
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}

            {sending && (
              <div className="flex justify-start">
                <div className="flex items-center gap-2 rounded-2xl bg-slate-100 px-3.5 py-2.5 text-[13px] text-slate-500">
                  <Spinner className="text-edb-500" width={15} height={15} /> Looking it up…
                </div>
              </div>
            )}
            <div ref={endRef} />
          </div>

          {/* input */}
          <form
            className="flex items-center gap-2 border-t border-slate-100 p-3"
            onSubmit={(e) => {
              e.preventDefault();
              ask(input);
            }}
          >
            <input
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about the claim or a person…"
              className="flex-1 rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-edb-500 focus:outline-none"
            />
            <button
              type="submit"
              disabled={sending || !input.trim()}
              className="flex h-9 w-9 items-center justify-center rounded-xl bg-ink text-white disabled:opacity-40"
            >
              <Send width={16} height={16} />
            </button>
          </form>
        </div>
      )}
    </>
  );
}

function fileBase(f: string): string {
  return f.split("/").pop() || f;
}
