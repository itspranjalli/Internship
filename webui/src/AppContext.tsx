import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { analyzeStream, getHealth, sendChat, type AnalyzeInputs } from "./api";
import { mergeInputs } from "./lib/docs";
import type { AnalysisResult, ChatMessage, Health, ProgressEvent } from "./types";
import type { Cite } from "./components/Evidence";

/** The result-driven pages are locked until an analysis has produced a result. */
export type Page =
  | "home"
  | "upload"
  | "doccheck"
  | "eligibility"
  | "claim"
  | "grant"
  | "pack"
  | "assistant";

export const RESULT_PAGES: Page[] = [
  "doccheck",
  "eligibility",
  "claim",
  "grant",
  "pack",
];

export type Status = "idle" | "analyzing" | "ready" | "error";

interface AppContextValue {
  // data
  health: Health | null;
  result: AnalysisResult | null;
  session: string | null;
  // flow
  status: Status;
  log: ProgressEvent[];
  pct: number;
  error: string | null;
  // ui
  advanced: boolean;
  setAdvanced: (v: boolean) => void;
  page: Page;
  setPage: (p: Page) => void;
  // evidence modal
  cite: Cite | null;
  openEvidence: (c: Cite) => void;
  closeEvidence: () => void;
  // actions
  analyze: (inputs: AnalyzeInputs) => Promise<void>;
  reset: () => void;
  reupload: (files: File[]) => void;
  // assistant (lifted so history survives navigation)
  messages: ChatMessage[];
  sending: boolean;
  ask: (q: string) => Promise<void>;
}

const AppContext = createContext<AppContextValue | null>(null);

export function useApp(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used within <AppProvider>");
  return ctx;
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [log, setLog] = useState<ProgressEvent[]>([]);
  const [pct, setPct] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const [page, setPage] = useState<Page>("home");
  const [cite, setCite] = useState<Cite | null>(null);
  const [lastInputs, setLastInputs] = useState<AnalyzeInputs | null>(null);
  // assistant
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sending, setSending] = useState(false);

  const session = result?.session ?? null;

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null));
  }, []);

  const openEvidence = useCallback((c: Cite) => setCite(c), []);
  const closeEvidence = useCallback(() => setCite(null), []);

  const analyze = useCallback(async (inputs: AnalyzeInputs) => {
    setLastInputs(inputs);
    setStatus("analyzing");
    setResult(null);
    setLog([]);
    setPct(0);
    setError(null);
    setMessages([]); // new run → new session; old citations no longer resolve
    setPage("upload"); // the Upload page hosts the inline progress screen
    try {
      await analyzeStream(inputs, (ev) => {
        if (ev.type === "progress") {
          setLog((prev) => [...prev, ev]);
          setPct(ev.pct);
        } else if (ev.type === "result") {
          setResult(ev.data);
          setStatus("ready");
          // land on the first result page once the workings are ready
          setTimeout(() => setPage("doccheck"), 450);
        } else if (ev.type === "error") {
          setError(ev.message);
          setStatus("error");
        }
      });
    } catch (e: any) {
      setError(String(e?.message || e));
      setStatus("error");
    }
  }, []);

  const reset = useCallback(() => {
    setResult(null);
    setStatus("idle");
    setLog([]);
    setPct(0);
    setError(null);
    setCite(null);
    setMessages([]);
    setPage("upload");
  }, []);

  const reupload = useCallback(
    (files: File[]) => {
      if (lastInputs && files.length) analyze(mergeInputs(lastInputs, files));
    },
    [lastInputs, analyze]
  );

  const ask = useCallback(
    async (q: string) => {
      const question = q.trim();
      if (!question || sending || !session) return;
      setMessages((m) => [...m, { role: "user", text: question }]);
      setSending(true);
      try {
        const ans = await sendChat(session, question);
        setMessages((m) => [
          ...m,
          { role: "assistant", text: ans.text, citations: ans.citations, mode: ans.mode },
        ]);
      } catch (e: any) {
        setMessages((m) => [...m, { role: "assistant", text: `Sorry — ${String(e?.message || e)}` }]);
      } finally {
        setSending(false);
      }
    },
    [sending, session]
  );

  // ⌘K / Ctrl-K jumps to the assistant (registered once, app-wide)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPage("assistant");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const value: AppContextValue = {
    health,
    result,
    session,
    status,
    log,
    pct,
    error,
    advanced,
    setAdvanced,
    page,
    setPage,
    cite,
    openEvidence,
    closeEvidence,
    analyze,
    reset,
    reupload,
    messages,
    sending,
    ask,
  };

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}
