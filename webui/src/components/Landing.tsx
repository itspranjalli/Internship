import { useCallback, useMemo, useRef, useState } from "react";
import type { AnalyzeInputs } from "../api";
import type { Health, Supporting } from "../types";
import { Check, Chevron, FileIcon, Shield, Upload, X } from "./icons";
import {
  ALL_SUPPORTING_TRUE, KIND_LABEL, SUPPORTING_FIELDS, detectSupporting, guessKind,
  type Kind,
} from "../lib/docs";

interface Tagged {
  file: File;
  kind: Kind;
}

export default function Landing({
  health,
  busy,
  onAnalyze,
}: {
  health: Health | null;
  busy: boolean;
  onAnalyze: (inputs: AnalyzeInputs) => void;
}) {
  const [tagged, setTagged] = useState<Tagged[]>([]);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // The checklist fills PROGRESSIVELY: each supporting item lights up green as we
  // recognise a matching file from its name. READ-ONLY — no manual ticking.
  const supporting = useMemo<Supporting>(
    () => detectSupporting(tagged.map((t) => t.file.name)),
    [tagged]
  );

  const addFiles = useCallback((files: FileList | File[]) => {
    const next: Tagged[] = [];
    for (const f of Array.from(files)) {
      if (!f.name.toLowerCase().endsWith(".xlsx")) continue;
      next.push({ file: f, kind: guessKind(f.name) });
    }
    if (next.length) setTagged((prev) => [...prev, ...next]);
  }, []);

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
  };

  const hasTimesheet = useMemo(() => tagged.some((t) => t.kind === "timesheet"), [tagged]);

  const submitUpload = () => {
    onAnalyze({
      mode: "upload",
      edbTemplate: tagged.find((t) => t.kind === "edb_template")?.file ?? null,
      trainee: tagged.find((t) => t.kind === "trainee")?.file ?? null,
      timesheets: tagged.filter((t) => t.kind === "timesheet").map((t) => t.file),
      rse: tagged.find((t) => t.kind === "rse")?.file ?? null,
      payroll: tagged.filter((t) => t.kind === "payroll").map((t) => t.file),
      supporting,
    });
  };

  const submitSample = () =>
    onAnalyze({ mode: "sample", edbTemplate: null, trainee: null, timesheets: [], rse: null, payroll: [], supporting: ALL_SUPPORTING_TRUE });

  // Guided order: EDB template → trainee list → timesheet → ECMF → payroll.
  // Each ticks as it's recognised; supporting docs appear as they're added.
  const core = [
    { label: "EDB output template", present: tagged.some((t) => t.kind === "edb_template") },
    { label: "Trainee list", present: tagged.some((t) => t.kind === "trainee") },
    { label: "Team timesheet", present: hasTimesheet },
    { label: "ECMF researcher list", present: tagged.some((t) => t.kind === "rse") },
    { label: "Payroll / payslips", present: tagged.some((t) => t.kind === "payroll") },
  ];
  const addedSupporting = SUPPORTING_FIELDS.filter((f) => f.key !== "trainee" && supporting[f.key]);
  const dot = (
    <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-emerald-500 text-white">
      <Check width={11} height={11} strokeWidth={3} />
    </span>
  );

  const requiredDone = core.filter((c) => c.present).length;

  return (
    <div className="relative">
      {/* soft hero backdrop for depth */}
      <div className="pointer-events-none absolute inset-x-0 top-0 h-80 bg-gradient-to-b from-edb-50/80 via-edb-50/20 to-transparent" />

      <div className="relative mx-auto max-w-6xl px-5 pb-28 pt-12 animate-fade-up sm:pt-16">
        <div className="max-w-2xl">
          <h1 className="mt-4 text-[2rem] font-extrabold leading-[1.1] tracking-tight text-ink sm:text-[2.6rem]">
            Prepare your EDB claim,<br className="hidden sm:block" /> the easy way.
          </h1>
          <p className="mt-3 text-[15px] leading-relaxed text-slate-500">
            Add your HR documents — we read them, check eligibility, calculate every person's claim and
            assemble the audit-ready pack. The checklist on the left fills in as each document is recognised.
          </p>
        </div>

        <div className="mt-9 flex flex-col gap-6 lg:flex-row">
          {/* LEFT — a live tracker that fills as documents are uploaded */}
          <aside className="lg:w-[18.5rem] lg:shrink-0">
            <div className="card overflow-hidden lg:sticky lg:top-24">
              <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50/60 px-4 py-3">
                <div className="flex items-center gap-2">
                  <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-edb-50 text-edb-600">
                    <Shield width={15} height={15} />
                  </span>
                  <div className="text-sm font-semibold text-ink">Documents</div>
                </div>
                <span className="rounded-full bg-white px-2 py-0.5 text-[11px] font-semibold text-slate-500 ring-1 ring-slate-200">
                  {requiredDone}/{core.length}
                </span>
              </div>

              <div className="p-4">
                <div className="text-[10px] font-bold uppercase tracking-wide text-slate-400">Required · in order</div>
                <ul className="mt-2 space-y-1">
                  {core.map((c, i) => (
                    <li key={c.label} className="flex items-center gap-2.5">
                      {c.present ? dot : (
                        <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-slate-300 text-[9px] font-bold text-slate-400">
                          {i + 1}
                        </span>
                      )}
                      <span className={"flex-1 text-[13px] " + (c.present ? "font-medium text-slate-700" : "text-slate-500")}>{c.label}</span>
                      {!c.present && (
                        <span className="text-[10px] font-semibold uppercase tracking-wide text-amber-500">needed</span>
                      )}
                    </li>
                  ))}
                </ul>

                <div className="my-3 border-t border-slate-100" />
                <div className="flex items-center justify-between">
                  <div className="text-[10px] font-bold uppercase tracking-wide text-slate-400">Supporting evidence</div>
                  <span className="text-[10px] font-medium text-slate-400">{addedSupporting.length} added</span>
                </div>
                {addedSupporting.length === 0 ? (
                  <p className="mt-1.5 text-[12px] leading-relaxed text-slate-400">
                    Leave report, CPF/bank, progress reports… appear here as you add them.
                  </p>
                ) : (
                  <ul className="mt-2 space-y-1 animate-fade-in">
                    {addedSupporting.map((f) => (
                      <li key={f.key} className="flex items-center gap-2.5">
                        {dot}
                        <span className="text-[13px] text-slate-700">{f.label}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </aside>

          {/* RIGHT — upload + actions */}
          <div className="min-w-0 flex-1">
            <div
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              onClick={() => inputRef.current?.click()}
              className={
                "group cursor-pointer rounded-3xl border-2 border-dashed p-12 text-center transition-all duration-200 " +
                (dragging
                  ? "border-edb-400 bg-edb-50 scale-[1.01]"
                  : "border-slate-200 bg-white hover:border-edb-300 hover:bg-edb-50/40 hover:shadow-sm")
              }
            >
              <input ref={inputRef} type="file" multiple accept=".xlsx" className="hidden"
                onChange={(e) => e.target.files && addFiles(e.target.files)} />
              <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-edb-500 to-edb-700 text-white shadow-lg shadow-edb-500/25 transition-transform duration-200 group-hover:scale-105">
                <Upload width={26} height={26} />
              </div>
              <div className="mt-5 text-lg font-semibold text-ink">Drop your documents here</div>
              <div className="mt-1 text-sm text-slate-400">or click to browse · Excel (.xlsx)</div>
            </div>

            {tagged.length > 0 && (
              <div className="mt-4 space-y-2 animate-fade-in">
                {tagged.map((t, i) => (
                  <div key={i} className="card flex items-center gap-3 px-4 py-2.5 transition-shadow hover:shadow-sm">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-edb-50 text-edb-600">
                      <FileIcon />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-ink">{t.file.name}</div>
                      <div className="text-xs text-slate-400">{(t.file.size / 1024).toFixed(0)} KB</div>
                    </div>
                    <select
                      value={t.kind}
                      onChange={(e) => setTagged((prev) => prev.map((x, j) => (j === i ? { ...x, kind: e.target.value as Kind } : x)))}
                      className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-600 focus:border-edb-500 focus:outline-none"
                    >
                      {(Object.keys(KIND_LABEL) as Kind[]).map((k) => (
                        <option key={k} value={k}>{KIND_LABEL[k]}</option>
                      ))}
                    </select>
                    <button
                      onClick={(e) => { e.stopPropagation(); setTagged((prev) => prev.filter((_, j) => j !== i)); }}
                      className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                    >
                      <X width={16} height={16} />
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div className="mt-7 flex flex-wrap items-center gap-x-5 gap-y-2">
              <button className="btn-primary px-9 py-3 text-[15px]"
                disabled={busy || !hasTimesheet} onClick={submitUpload}>
                Analyse documents →
              </button>
              {health?.sample_available && (
                <button className="text-sm font-medium text-slate-500 hover:text-edb-600 disabled:opacity-40"
                  disabled={busy} onClick={submitSample}>
                  or explore with sample data →
                </button>
              )}
              {!hasTimesheet && (
                <p className="w-full text-xs text-slate-400">Add at least a team timesheet to continue.</p>
              )}
            </div>

            <details className="group mt-8 rounded-2xl border border-slate-200 bg-white">
              <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-sm font-semibold text-ink [&::-webkit-details-marker]:hidden">
                What format does each document need?
                <Chevron className="text-slate-400 transition-transform group-open:rotate-90" width={16} height={16} />
              </summary>
              <div className="space-y-2 border-t border-slate-100 px-4 py-3 text-[13px] leading-relaxed text-slate-600">
                <p><b className="text-ink">EDB output template</b> — the blank RIS(C) v1.1 export (.xlsx); the system fills it for you.</p>
                <p><b className="text-ink">Trainee list</b> — any sheet listing trainees (Employee ID, Name, training start/end).</p>
                <p><b className="text-ink">Team timesheet</b> — one workbook with <b>two tabs</b>:
                  <code className="mx-1 rounded bg-slate-100 px-1">Time Sheet</code>(hours, row 19+) and
                  <code className="mx-1 rounded bg-slate-100 px-1">Staff Costs</code>(join/leave dates, row 15+).</p>
                <p><b className="text-ink">ECMF researcher list</b> — columns: Employee ID, Name, Citizenship, ECMF Validated.</p>
                <p><b className="text-ink">Payroll / payslips</b> — a register (sheet <code className="rounded bg-slate-100 px-1">Payroll</code> or
                  <code className="mx-1 rounded bg-slate-100 px-1">Payslip</code>) with Employee ID, Year+Month (or a Pay Date) and Basic Salary.
                  Or one payslip per file named like <code className="rounded bg-slate-100 px-1">payslip-E001-2026-01.xlsx</code>. CPF/bonus/allowances are ignored.</p>
                <p className="text-[11px] text-slate-400">Ready-made example files in the exact format: <code>docs/demo/testkit/</code></p>
              </div>
            </details>

            <p className="mt-6 flex items-center gap-1.5 text-xs text-slate-400">
              🔒 Your files stay on this machine — nothing is uploaded to the internet.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
