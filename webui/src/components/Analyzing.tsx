import { useEffect, useRef } from "react";
import type { ProgressEvent } from "../types";
import { Check, Spinner, X } from "./icons";

export default function Analyzing({
  log,
  pct,
  error,
  onReset,
}: {
  log: ProgressEvent[];
  pct: number;
  error: string | null;
  onReset: () => void;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), [log.length]);

  const current = log[log.length - 1];
  const done = error ? log : log.slice(0, -1);

  return (
    <div className="mx-auto flex max-w-2xl flex-col px-5 pt-16 sm:pt-24 animate-fade-up">
      <div className="card overflow-hidden">
        <div className="border-b border-slate-100 px-7 pt-7">
          <div className="flex items-center gap-3">
            {error ? (
              <span className="flex h-9 w-9 items-center justify-center rounded-full bg-red-50 text-red-600">
                <X />
              </span>
            ) : pct >= 100 ? (
              <span className="flex h-9 w-9 items-center justify-center rounded-full bg-emerald-50 text-emerald-600">
                <Check />
              </span>
            ) : (
              <Spinner className="text-edb-500" width={26} height={26} />
            )}
            <div>
              <div className="text-lg font-semibold text-ink">
                {error ? "Something went wrong" : pct >= 100 ? "Analysis complete" : "Analysing your claim"}
              </div>
              <div className="text-xs text-slate-400">
                {error ? "No figures were changed." : `${pct}% · reading documents and applying EDB's rules`}
              </div>
            </div>
          </div>

          {/* progress bar */}
          <div className="mt-5 mb-6 h-2 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className={
                "h-full rounded-full transition-all duration-500 ease-out " +
                (error ? "bg-red-500" : "bg-gradient-to-r from-edb-500 to-edb-700")
              }
              style={{ width: `${error ? 100 : pct}%` }}
            />
          </div>
        </div>

        {/* step log */}
        <div className="max-h-[44vh] overflow-y-auto px-7 py-5">
          <ol className="space-y-3.5">
            {done.map((ev, i) => (
              <li key={i} className="flex gap-3 animate-fade-in">
                <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
                  <Check width={13} height={13} strokeWidth={3} />
                </span>
                <div>
                  <div className="text-sm font-medium text-slate-700">{ev.label}</div>
                  {ev.detail && <div className="text-xs text-slate-400">{ev.detail}</div>}
                </div>
              </li>
            ))}
            {!error && current && pct < 100 && (
              <li className="flex gap-3">
                <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center">
                  <Spinner className="text-edb-500" width={16} height={16} />
                </span>
                <div>
                  <div className="text-sm font-semibold text-ink">{current.label}</div>
                  {current.detail && <div className="text-xs text-slate-400">{current.detail}</div>}
                </div>
              </li>
            )}
            {error && (
              <li className="flex gap-3">
                <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-red-100 text-red-600">
                  <X width={13} height={13} strokeWidth={3} />
                </span>
                <div className="text-sm text-red-700">{error}</div>
              </li>
            )}
            <div ref={endRef} />
          </ol>
        </div>
      </div>

      {error && (
        <button className="btn-outline mx-auto mt-6" onClick={onReset}>
          ← Back to upload
        </button>
      )}
    </div>
  );
}
