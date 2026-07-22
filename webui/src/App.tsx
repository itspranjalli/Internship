import { useEffect, useState } from "react";
import { analyzeStream, getHealth, type AnalyzeInputs } from "./api";
import { mergeInputs } from "./lib/docs";
import type { AnalysisResult, Health, ProgressEvent } from "./types";
import Landing from "./components/Landing";
import Analyzing from "./components/Analyzing";
import Results from "./components/Results";
import Evidence, { type Cite } from "./components/Evidence";
import Chat from "./components/Chat";

type Phase = "landing" | "analyzing" | "results";

export default function App() {
  const [phase, setPhase] = useState<Phase>("landing");
  const [health, setHealth] = useState<Health | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [log, setLog] = useState<ProgressEvent[]>([]);
  const [pctVal, setPctVal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const [cite, setCite] = useState<Cite | null>(null);
  const [lastInputs, setLastInputs] = useState<AnalyzeInputs | null>(null);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null));
  }, []);

  const reset = () => {
    setPhase("landing");
    setResult(null);
    setLog([]);
    setPctVal(0);
    setError(null);
    setCite(null);
  };

  const handleAnalyze = async (inputs: AnalyzeInputs) => {
    setLastInputs(inputs);
    setPhase("analyzing");
    setLog([]);
    setPctVal(0);
    setError(null);
    try {
      await analyzeStream(inputs, (ev) => {
        if (ev.type === "progress") {
          setLog((prev) => [...prev, ev]);
          setPctVal(ev.pct);
        } else if (ev.type === "result") {
          setResult(ev.data);
          setTimeout(() => setPhase("results"), 450);
        } else if (ev.type === "error") {
          setError(ev.message);
        }
      });
    } catch (e: any) {
      setError(String(e?.message || e));
    }
  };

  return (
    <div className="min-h-full font-sans">
      <TopBar
        health={health}
        advanced={advanced}
        setAdvanced={setAdvanced}
        showReset={phase === "results"}
        onReset={reset}
      />

      {phase === "landing" && (
        <Landing health={health} busy={false} onAnalyze={handleAnalyze} />
      )}
      {phase === "analyzing" && (
        <Analyzing log={log} pct={pctVal} error={error} onReset={reset} />
      )}
      {phase === "results" && result && (
        <Results
          result={result}
          advanced={advanced}
          onCite={setCite}
          onReupload={(files) => {
            if (lastInputs && files.length) handleAnalyze(mergeInputs(lastInputs, files));
          }}
        />
      )}

      {phase === "results" && result && (
        <Chat
          session={result.session}
          llmEnabled={!!health?.llm_enabled}
          onCite={setCite}
        />
      )}

      {result && cite && (
        <Evidence session={result.session} cite={cite} onClose={() => setCite(null)} />
      )}
    </div>
  );
}

function TopBar({
  health,
  advanced,
  setAdvanced,
  showReset,
  onReset,
}: {
  health: Health | null;
  advanced: boolean;
  setAdvanced: (v: boolean) => void;
  showReset: boolean;
  onReset: () => void;
}) {
  return (
    <header className="sticky top-0 z-40 border-b border-slate-200/70 bg-white/80 backdrop-blur-md">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-3">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-edb-500 to-edb-700 text-[13px] font-bold text-white shadow-sm shadow-edb-500/20">
            ED
          </span>
          <div className="leading-tight">
            <div className="text-[15px] font-bold tracking-tight text-ink">EDB Grant Compliance</div>
            <div className="text-[11px] text-slate-400">
              ST Engineering · HR{health && ` · ${health.application_no}`}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Simple / Advanced segmented toggle */}
          <div className="flex rounded-lg bg-slate-100 p-0.5 text-xs font-semibold">
            <button
              onClick={() => setAdvanced(false)}
              className={"rounded-md px-3 py-1.5 transition-colors " + (!advanced ? "bg-white text-ink shadow-sm" : "text-slate-500")}
            >
              Simple
            </button>
            <button
              onClick={() => setAdvanced(true)}
              className={"rounded-md px-3 py-1.5 transition-colors " + (advanced ? "bg-white text-ink shadow-sm" : "text-slate-500")}
            >
              Advanced
            </button>
          </div>

          {showReset && (
            <button className="btn-primary px-3.5 py-2 text-xs" onClick={onReset}>
              New claim
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
