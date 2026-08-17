import { Fragment, useEffect, useRef, useState } from "react";
import { downloadUrl, listDownloads } from "../api";
import type { AnalysisResult, Employee, Entity, EvidenceRef, MatrixCell, MonthRow } from "../types";
import { money, pct, prettyDate, ym } from "../lib/format";
import type { Cite } from "./Evidence";
import { Alert, Check, Chevron, Doc, Download, Search, Upload, X } from "./icons";

const MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
// per-month conditions, not "documents" — kept out of the document tracker
const CONDITION_DOCS = new Set(["hours_over_capacity", "payslip_ne_staff_costs_a"]);

const STATUS_STYLE: Record<string, { label: string; cls: string }> = {
  QUALIFIES: { label: "Qualifies", cls: "bg-emerald-50 text-emerald-700" },
  EXCLUDED: { label: "Not eligible", cls: "bg-red-50 text-red-700" },
  BLOCKED: { label: "Needs a document", cls: "bg-amber-50 text-amber-700" },
};

/**
 * The four headline metrics + the non-final banner. Shown on the Overview page.
 * (Previously the header of the tabbed Results view; the sidebar now owns tabs.)
 */
export function ResultsSummary({ result }: { result: AnalysisResult }) {
  const c = result.counts;
  const everyone = result.entities.flatMap((e) => e.employees);
  // "Claimable" = eligible AND a real claim (> $0). Someone who passes the gates
  // but has a $0 claim (e.g. no project hours) is NOT counted here — they're
  // surfaced under review instead.
  const claimable = everyone.filter((e) => e.qualifies && e.claim_amount > 0).length;
  const pendingHours = everyone.filter((e) => e.zero_claim).length;

  return (
    <div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric label="Claimable" value={claimable} tone="emerald"
          sub={pendingHours ? `+${pendingHours} eligible, $0 (no hours)` : undefined} />
        <Metric label="Needs a document" value={c.blocked} tone="amber" />
        <Metric label="Not eligible" value={c.excluded} tone="red" />
        <Metric label="Total claim" value={money(result.total_claim_a)} tone="ink" />
      </div>

      {!result.support_rate_is_final && (
        <div className="mt-4 flex items-start gap-2 rounded-xl bg-edb-50 px-4 py-3 text-[13px] text-edb-700">
          <span className="mt-0.5">ℹ️</span>
          <span>
            Figures use an assumed {pct(result.support_rate)} support rate (EDB confirms the exact
            rate in the Letter of Award), so they are marked <strong>non-final</strong>.
          </span>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value, tone, sub }: { label: string; value: string | number; tone: string; sub?: string }) {
  const color =
    { emerald: "text-emerald-600", amber: "text-amber-600", red: "text-red-600", ink: "text-ink" }[
      tone
    ] || "text-ink";
  return (
    <div className="card px-4 py-3">
      <div className="text-xs font-medium text-slate-400">{label}</div>
      <div className={"mt-1 text-2xl font-bold " + color}>{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-amber-600">{sub}</div>}
    </div>
  );
}

function CiteBtn({ cell, onCite }: { cell: MatrixCell; onCite: (c: Cite) => void }) {
  if (!cell.source) return null;
  return (
    <button
      onClick={() =>
        onCite({
          file: cell.source!.file,
          sheet: cell.source!.sheet,
          cell: cell.source!.cell,
          label: cell.source!.label || cell.doc_label,
        })
      }
      className="rounded-md p-1 text-slate-400 hover:bg-edb-50 hover:text-edb-600"
      title="View the source document"
    >
      <Search width={15} height={15} />
    </button>
  );
}

/* ---------------------------------------------------------------- Doc check */
interface PersonGroup { key: string; label: string; present: number; total: number; missing: MatrixCell[]; }

function buildGroups(ent: Entity): { company: MatrixCell[]; groups: PersonGroup[] } {
  const company = ent.cells.filter((c) => c.scope === "entity" && !CONDITION_DOCS.has(c.doc_type));
  const map = new Map<string, PersonGroup>();
  for (const c of ent.cells) {
    if (c.scope === "entity" || CONDITION_DOCS.has(c.doc_type)) continue;
    let g = map.get(c.doc_type);
    if (!g) { g = { key: c.doc_type, label: c.doc_label, present: 0, total: 0, missing: [] }; map.set(c.doc_type, g); }
    g.total++;
    if (c.status === "present") g.present++; else g.missing.push(c);
  }
  return { company, groups: Array.from(map.values()) };
}

function shortEntity(name: string): string {
  return name.replace("ST Engineering", "STE").replace(" Pte Ltd", "").replace(" Ltd", "");
}

function StatusIcon({ ok, severity }: { ok: boolean; severity?: string }) {
  if (ok)
    return (
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
        <Check width={13} height={13} strokeWidth={3} />
      </span>
    );
  const red = severity === "BLOCKER";
  return (
    <span className={"flex h-5 w-5 shrink-0 items-center justify-center rounded-full " + (red ? "bg-red-100 text-red-600" : "bg-amber-100 text-amber-600")}>
      <X width={12} height={12} strokeWidth={3} />
    </span>
  );
}

function MiniStatus({ c }: { c: MatrixCell }) {
  if (c.status === "present")
    return <Check className="shrink-0 text-emerald-500" width={13} height={13} strokeWidth={3} />;
  return <X className={"shrink-0 " + (c.severity === "BLOCKER" ? "text-red-500" : "text-amber-500")}
    width={12} height={12} strokeWidth={3} />;
}

function EntityTracker({ ent, onCite, view }: { ent: Entity; onCite: (c: Cite) => void; view: "doc" | "person" }) {
  const { company, groups } = buildGroups(ent);
  const names = new Map(ent.employees.map((e) => [e.id, e.name] as const));
  const [open, setOpen] = useState<string | null>(null);
  const empCells = (id: string) =>
    ent.cells.filter((c) => c.employee_id === id && !CONDITION_DOCS.has(c.doc_type));
  return (
    <div className="card p-5">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3">
        <div className="font-semibold text-ink">{ent.entity}</div>
        <div className="flex gap-3 text-xs text-slate-500">
          <span><b className="text-emerald-600">{ent.rollup.ready_count}</b> ready</span>
          <span><b className="text-amber-600">{ent.rollup.blocked_count}</b> waiting</span>
          <span><b className="text-ink">{ent.rollup.employee_count}</b> staff</span>
        </div>
      </div>

      <div className="mt-3 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Per company</div>
      <ul className="mt-1 space-y-0.5">
        {company.map((c, i) => (
          <li key={i} className="flex items-center gap-2.5 py-1">
            <StatusIcon ok={c.status === "present"} severity={c.severity} />
            <span className="flex-1 text-sm capitalize text-slate-700">{c.doc_label}</span>
            {c.status === "present"
              ? <CiteBtn cell={c} onCite={onCite} />
              : <span className="text-[11px] font-medium text-slate-400">missing</span>}
          </li>
        ))}
      </ul>

      {/* ---- BY DOCUMENT: grouped per doc type with present/total counts ---- */}
      {view === "doc" && groups.length > 0 && (
        <>
          <div className="mt-4 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Per person</div>
          <ul className="mt-1 space-y-0.5">
            {groups.map((g) => {
              const ok = g.missing.length === 0;
              const isOpen = open === g.key;
              return (
                <li key={g.key}>
                  <button
                    onClick={() => g.missing.length && setOpen(isOpen ? null : g.key)}
                    className="flex w-full items-center gap-2.5 py-1 text-left"
                  >
                    <StatusIcon ok={ok} severity={g.missing[0]?.severity} />
                    <span className="flex-1 text-sm capitalize text-slate-700">{g.label}</span>
                    <span className={"text-xs font-semibold " + (ok ? "text-emerald-600" : "text-amber-600")}>
                      {g.present}/{g.total}
                    </span>
                    {g.missing.length > 0 && (
                      <Chevron className={"text-slate-300 transition-transform " + (isOpen ? "rotate-90" : "")} width={14} height={14} />
                    )}
                  </button>
                  {isOpen && (
                    <ul className="mb-1 ml-7 space-y-1 border-l border-slate-100 pl-3 animate-fade-in">
                      {g.missing.map((c, i) => (
                        <li key={i} className="text-[13px] text-slate-500">
                          {c.month ? `${MONTH_ABBR[c.month]} · ` : ""}
                          {names.get(c.employee_id || "") || c.employee_id}
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}

      {/* ---- BY PERSON: validate each employee's name against their docs ---- */}
      {view === "person" && ent.employees.length > 0 && (
        <>
          <div className="mt-4 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Per person — name × documents</div>
          <ul className="mt-1 space-y-0.5">
            {ent.employees.map((emp) => {
              const cells = empCells(emp.id);
              const miss = cells.filter((c) => c.status !== "present");
              const ok = miss.length === 0;
              const isOpen = open === emp.id;
              return (
                <li key={emp.id}>
                  <button
                    onClick={() => setOpen(isOpen ? null : emp.id)}
                    className="flex w-full items-center gap-2.5 py-1 text-left"
                  >
                    <StatusIcon ok={ok} severity={miss[0]?.severity} />
                    <span className="flex-1 truncate text-sm text-slate-700">
                      {emp.name} <span className="text-slate-400">· {emp.id}</span>
                    </span>
                    <span className={"text-xs font-semibold " + (ok ? "text-emerald-600" : "text-amber-600")}>
                      {ok ? "all present" : `${miss.length} missing`}
                    </span>
                    <Chevron className={"text-slate-300 transition-transform " + (isOpen ? "rotate-90" : "")} width={14} height={14} />
                  </button>
                  {isOpen && (
                    <ul className="mb-1 ml-7 grid grid-cols-1 gap-x-4 border-l border-slate-100 pl-3 animate-fade-in sm:grid-cols-2">
                      {cells.map((c, i) => (
                        <li key={i} className="flex items-center gap-2 py-0.5">
                          <MiniStatus c={c} />
                          <span className="flex-1 truncate text-[12px] capitalize text-slate-600">
                            {c.doc_label}{c.month ? ` · ${MONTH_ABBR[c.month]}` : ""}
                          </span>
                          {c.status === "present" && c.source && <CiteBtn cell={c} onCite={onCite} />}
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}

export function DocCheck({ result, onCite, onReupload }: {
  result: AnalysisResult; onCite: (c: Cite) => void; onReupload: (files: File[]) => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [view, setView] = useState<"doc" | "person">("doc");
  const missing = result.entities.flatMap((e) =>
    e.cells
      .filter((c) => c.status === "missing" && !CONDITION_DOCS.has(c.doc_type))
      .map((c) => ({ ...c, _entity: e.entity }))
  );
  const names = new Map(result.entities.flatMap((e) => e.employees.map((x) => [x.id, x.name] as const)));
  const blockers = missing.filter((m) => m.severity === "BLOCKER");

  return (
    <div className="flex flex-col gap-5 lg:flex-row">
      {/* LEFT — the tracked document checklist */}
      <div className="min-w-0 flex-1 space-y-4">
        {result.errors.length > 0 && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4">
            <div className="flex items-center gap-2 text-sm font-bold text-red-700">
              <Alert width={18} height={18} />
              {result.errors.length} file(s) couldn't be read — here's why
            </div>
            <ul className="mt-2 space-y-2">
              {result.errors.map((e, i) => {
                const colon = e.indexOf(":");
                const head = colon > 0 ? e.slice(0, colon) : e;
                const body = colon > 0 ? e.slice(colon + 1).trim() : "";
                return (
                  <li key={i} className="text-[13px] leading-relaxed text-red-800">
                    <span className="font-semibold">{head}</span>
                    {body && <span className="text-red-700"> — {body}</span>}
                  </li>
                );
              })}
            </ul>
            <p className="mt-2 text-[11px] text-red-500">
              Fix the file and re-upload it from the panel on the right — everything else was still processed.
            </p>
          </div>
        )}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-slate-500">
            We check your uploads against the required list and tick what's present — down to each
            person's payslip. Anything outstanding is on the right.
          </p>
          <div className="flex shrink-0 rounded-lg bg-slate-100 p-0.5 text-xs font-semibold">
            <button
              onClick={() => setView("doc")}
              className={"rounded-md px-3 py-1.5 transition-colors " + (view === "doc" ? "bg-white text-ink shadow-sm" : "text-slate-500")}
            >
              By document
            </button>
            <button
              onClick={() => setView("person")}
              className={"rounded-md px-3 py-1.5 transition-colors " + (view === "person" ? "bg-white text-ink shadow-sm" : "text-slate-500")}
            >
              By person
            </button>
          </div>
        </div>
        {result.entities.map((ent) => <EntityTracker key={ent.entity} ent={ent} onCite={onCite} view={view} />)}
      </div>

      {/* RIGHT — what's missing, at eye level (sticky) */}
      <div className="lg:w-[21rem] lg:shrink-0">
        <div className="lg:sticky lg:top-24">
          <div className="card overflow-hidden">
            <div className={"px-5 py-3 " + (missing.length ? "bg-amber-50" : "bg-emerald-50")}>
              <div className="flex items-center gap-2">
                {missing.length
                  ? <Alert width={18} height={18} className="text-amber-600" />
                  : <Check width={18} height={18} className="text-emerald-600" />}
                <div className={"text-sm font-bold " + (missing.length ? "text-amber-800" : "text-emerald-700")}>
                  {missing.length
                    ? `${missing.length} document${missing.length > 1 ? "s" : ""} still missing`
                    : "All documents present"}
                </div>
              </div>
              {blockers.length > 0 && (
                <div className="mt-0.5 text-[11px] font-semibold text-red-600">{blockers.length} blocking the claim</div>
              )}
            </div>

            {missing.length > 0 && (
              <ul className="max-h-[46vh] divide-y divide-slate-100 overflow-y-auto">
                {missing.map((m, i) => (
                  <li key={i} className="flex items-start gap-2.5 px-4 py-2.5">
                    <span className={"mt-1 h-2 w-2 shrink-0 rounded-full " + (m.severity === "BLOCKER" ? "bg-red-500" : "bg-amber-500")} />
                    <div className="min-w-0">
                      <div className="text-[13px] font-medium capitalize text-slate-700">
                        {m.doc_label}{m.month ? ` · ${MONTH_ABBR[m.month]}` : ""}
                      </div>
                      <div className="truncate text-[11px] text-slate-400">
                        {(m.employee_id ? (names.get(m.employee_id) || m.employee_id) : "company")} · {shortEntity(m._entity)}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}

            <div className="border-t border-slate-100 p-3">
              <input ref={fileRef} type="file" accept=".xlsx" multiple className="hidden"
                onChange={(e) => { if (e.target.files?.length) onReupload(Array.from(e.target.files)); }} />
              <button className="btn-primary w-full" onClick={() => fileRef.current?.click()}>
                <Upload width={16} height={16} /> Upload missing documents
              </button>
              <p className="mt-2 text-center text-[11px] text-slate-400">
                Add the updated file(s) — we merge and re-check automatically.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- Eligibility */
export function Eligibility({ result }: { result: AnalysisResult }) {
  const [filter, setFilter] = useState<"All" | "Qualifying" | "Not claimed" | "Needs review">("All");
  const all = result.entities.flatMap((e) => e.employees);
  const shown = all.filter((e) => {
    if (filter === "Qualifying") return e.status === "QUALIFIES";
    if (filter === "Not claimed") return e.status !== "QUALIFIES";
    if (filter === "Needs review") return e.needs_review;
    return true;
  });
  return (
    <div>
      <p className="mb-4 text-sm text-slate-500">
        Every person is checked against EDB's criteria. Nobody is silently dropped — those not
        claimed are shown with the reason.
      </p>
      <div className="mb-4 flex gap-1 overflow-x-auto rounded-xl bg-slate-100 p-1 text-sm">
        {(["All", "Qualifying", "Not claimed", "Needs review"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={
              "whitespace-nowrap rounded-lg px-3 py-1.5 font-medium transition-colors " +
              (filter === f ? "bg-white text-ink shadow-sm" : "text-slate-500 hover:text-slate-700")
            }
          >
            {f}
          </button>
        ))}
      </div>
      <div className="space-y-2">
        {shown.map((e) => (
          <PersonRow key={e.id} e={e} />
        ))}
      </div>
    </div>
  );
}

function PersonRow({ e }: { e: Employee }) {
  const [open, setOpen] = useState(false);
  const st = STATUS_STYLE[e.status];
  return (
    <div className="card overflow-hidden">
      <button
        onClick={() => setOpen((s) => !s)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        <Chevron
          className={"shrink-0 text-slate-400 transition-transform " + (open ? "rotate-90" : "")}
          width={16}
          height={16}
        />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-ink">{e.name}</div>
          <div className="truncate text-xs text-slate-400">
            {e.id} · {e.designation}
          </div>
        </div>
        {e.zero_claim ? (
          <span className="pill bg-amber-50 text-amber-700">Eligible · $0 — review</span>
        ) : (
          <>
            {e.needs_review && <span className="pill bg-edb-50 text-edb-600">review</span>}
            <span className={"pill " + st.cls}>{st.label}</span>
          </>
        )}
        <span className={"w-24 text-right text-sm font-semibold " + (e.zero_claim ? "text-amber-600" : "text-ink")}>
          {e.qualifies ? money(e.claim_amount) : ""}
        </span>
      </button>
      {open && (
        <div className="border-t border-slate-100 px-4 py-3 animate-fade-in">
          {e.zero_claim ? (
            <div className="mb-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
              Passes every eligibility check, but the claim is <b>$0</b> — no project hours are
              recorded for the claim window, so there is nothing to claim yet. Enter/verify this
              person's timesheet hours before filing.
            </div>
          ) : e.needs_review ? (
            <div className="mb-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
              This role is borderline — please confirm it is an eligible R&D role.
            </div>
          ) : null}
          <table className="w-full text-left text-[13px]">
            <tbody className="divide-y divide-slate-100">
              {e.gates.map((g) => (
                <tr key={g.code}>
                  <td className="py-2 pr-3 text-slate-600">{g.name}</td>
                  <td className="w-20 py-2">
                    <span
                      className={
                        "pill " + (g.passed ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700")
                      }
                    >
                      {g.passed ? "OK" : "Not met"}
                    </span>
                  </td>
                  <td className="py-2 pl-3 text-slate-400">{g.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {e.status !== "QUALIFIES" && e.reasons.length > 0 && (
            <div className="mt-3 text-sm">
              <span className="font-semibold text-slate-600">Why not claimed: </span>
              <span className="text-slate-500">{e.reasons.join("; ")}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------- Claim */
function SourceLink({
  src,
  label,
  onCite,
}: {
  src: EvidenceRef | null;
  label: string;
  onCite: (c: Cite) => void;
}) {
  if (!src) return null;
  return (
    <button
      onClick={(ev) => {
        ev.stopPropagation();
        onCite({ file: src.file, sheet: src.sheet, cell: src.cell, label: src.label || label });
      }}
      className="ml-1 inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium text-edb-600 hover:bg-edb-50"
      title="View the source document"
    >
      <Search width={11} height={11} /> {label}
    </button>
  );
}

function MonthLine({
  m,
  advanced,
  onCite,
}: {
  m: MonthRow;
  advanced: boolean;
  onCite: (c: Cite) => void;
}) {
  const monthWorked = m.full_month ? "100%" : `${(m.month_fraction * 100).toFixed(1)}%`;
  const timeOnProj = m.time_clamped ? "100%" : `${(m.time_contribution * 100).toFixed(1)}%`;
  return (
    <tr className="align-top">
      <td className="px-3 py-2 font-medium text-slate-700">{ym(m.year, m.month)}</td>
      <td className="px-3 py-2 text-slate-600">
        {money(m.capped_salary)}
        {m.salary_capped && <span className="ml-1 pill bg-amber-50 text-amber-700">capped</span>}
        <SourceLink src={m.salary_source} label="payslip" onCite={onCite} />
      </td>
      <td className="px-3 py-2 text-slate-600">
        {monthWorked}
        <div className="text-[11px] text-slate-400">
          {m.full_month ? "full month" : `${m.worked_weekdays}/${m.weekdays} weekdays worked`}
          {advanced && m.full_month && ` · ${m.weekdays} weekdays`}
        </div>
      </td>
      <td className="px-3 py-2 text-slate-600">
        {timeOnProj}
        <div className="text-[11px] text-slate-400">
          {m.time_clamped
            ? "hours ≥ capacity → clamped"
            : m.implied_hours != null
            ? `${m.implied_hours} / ${m.capacity_hours} hrs`
            : `of ${m.capacity_hours} hr capacity`}
          {advanced && ` · ${m.weekdays} wd × 8.8 = ${m.capacity_hours} hrs`}
        </div>
        <SourceLink src={m.hours_source} label="Time Sheet" onCite={onCite} />
      </td>
      <td className="px-3 py-2 text-right font-semibold text-ink">
        {money(m.qualifying_cost)}
        {advanced && (
          <div className="text-[11px] font-normal text-slate-400">
            {m.capped_salary.toFixed(2)} × {m.month_fraction.toFixed(4)} × {m.time_contribution.toFixed(4)}
          </div>
        )}
      </td>
    </tr>
  );
}

function CalcDetail({
  e,
  advanced,
  onCite,
}: {
  e: Employee;
  advanced: boolean;
  onCite: (c: Cite) => void;
}) {
  if (e.monthly.length === 0)
    return <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-500">No monthly workings recorded for this person.</div>;
  return (
    <div className="rounded-xl bg-slate-50 p-4 animate-fade-in">
      <p className="mb-3 text-[13px] leading-relaxed text-slate-500">
        For each month {e.name} is on the project:&nbsp;
        <b className="text-slate-700">capped salary × month worked × time on project</b>. The claim is
        the sum across months × the {pct(e.support_rate)} support rate. Salary is capped at{" "}
        {money(20000)}/month, time on project at 100%. Every figure links to its source document.
      </p>
      {e.months_capped > 0 && (
        <div className="mb-3 rounded-lg bg-amber-50 px-3 py-2 text-[12px] text-amber-800">
          Upskill/reskill to PL3 is funded for up to 9 months — <b>{e.months_capped}</b> later
          month(s) were excluded by the 9-month cap (earliest months kept).
        </div>
      )}
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-left text-[13px]">
          <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-400">
            <tr>
              <th className="px-3 py-2 font-semibold">Month</th>
              <th className="px-3 py-2 font-semibold">Capped basic salary</th>
              <th className="px-3 py-2 font-semibold">× Month worked</th>
              <th className="px-3 py-2 font-semibold">× Time on project</th>
              <th className="px-3 py-2 text-right font-semibold">= Qualifying cost</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {e.monthly.map((m, i) => (
              <MonthLine key={i} m={m} advanced={advanced} onCite={onCite} />
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t-2 border-slate-200 bg-slate-50 font-semibold text-slate-700">
              <td className="px-3 py-2" colSpan={4}>
                Total qualifying cost
              </td>
              <td className="px-3 py-2 text-right">{money(e.qualifying_cost_total)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg bg-ink px-4 py-2.5 text-white">
        <span className="text-sm text-slate-300">{money(e.qualifying_cost_total)}</span>
        <span className="text-sm text-slate-400">× {pct(e.support_rate)} support rate =</span>
        <span className="text-base font-bold">{money(e.claim_amount)}</span>
        <span className="ml-auto text-[11px] text-slate-400">EDB Method A — the submitted figure</span>
      </div>
    </div>
  );
}

export function Claim({
  result,
  advanced,
  onCite,
}: {
  result: AnalysisResult;
  advanced: boolean;
  onCite: (c: Cite) => void;
}) {
  const quals = result.entities.flatMap((e) => e.employees).filter((e) => e.qualifies && e.claim_amount > 0);
  const varianceRows = result.entities.flatMap((e) => e.variance.rows);
  const [showVariance, setShowVariance] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const nameById = new Map(
    result.entities.flatMap((e) => e.employees).map((e) => [e.id, e.name] as const)
  );
  return (
    <div>
      <p className="mb-3 text-sm text-slate-500">
        Calculated for the {quals.length} qualifying staff using EDB's monthly pro-ration. You don't
        enter any numbers — <b className="text-slate-600">open a person</b> to see exactly how their
        claim is worked out, traced to each source document.
      </p>

      {/* plain-English explainer of the two figures */}
      <div className="mb-4 grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl border border-edb-100 bg-edb-50/60 p-3.5">
          <div className="flex items-center gap-2 text-sm font-semibold text-edb-700">
            <span className="rounded bg-edb-600 px-1.5 py-0.5 text-[11px] font-bold text-white">A</span>
            EDB method — the figure we submit
          </div>
          <p className="mt-1.5 text-[13px] leading-relaxed text-slate-600">
            For each month: <b>60% of the capped salary</b>, scaled by <b>how much of the month</b>
            {" "}the person worked and <b>how much of their time</b> was on the project. Add the months up.
            <span className="text-slate-400"> This is what goes to EDB.</span>
          </p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-600">
            <span className="rounded bg-slate-400 px-1.5 py-0.5 text-[11px] font-bold text-white">B</span>
            Internal check — never submitted
          </div>
          <p className="mt-1.5 text-[13px] leading-relaxed text-slate-600">
            Your team's existing hours-based method (project hours ÷ total capacity). We run it
            quietly as a <b>second opinion</b>: if A and B differ a lot it usually means a data issue
            to fix. <span className="text-slate-400">“Cross-check OK” = they agree; “Review” = worth a look.</span>
          </p>
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-slate-200">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
            <tr>
              <th className="w-8 px-3 py-2" />
              <th className="px-3 py-2 font-semibold">Employee</th>
              <th className="px-3 py-2 font-semibold">Name</th>
              <th className="px-3 py-2 font-semibold">Monthly salary</th>
              <th className="px-3 py-2 font-semibold">Claim amount</th>
              <th className="px-3 py-2 font-semibold">Cross-check</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {quals.map((e) => {
              const open = openId === e.id;
              return (
                <Fragment key={e.id}>
                  <tr className="cursor-pointer hover:bg-slate-50" onClick={() => setOpenId(open ? null : e.id)}>
                    <td className="px-3 py-2">
                      <Chevron
                        className={"text-slate-400 transition-transform " + (open ? "rotate-90" : "")}
                        width={15}
                        height={15}
                      />
                    </td>
                    <td className="px-3 py-2 font-medium text-slate-700">{e.id}</td>
                    <td className="px-3 py-2 text-slate-600">{e.name}</td>
                    <td className="px-3 py-2 text-slate-600">{money(e.monthly_basic_salary)}</td>
                    <td className="px-3 py-2 font-semibold text-ink">{money(e.claim_amount)}</td>
                    <td className="px-3 py-2">
                      <span
                        className={
                          "pill " +
                          (e.crosscheck_ok ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700")
                        }
                      >
                        {e.crosscheck_ok ? "OK" : "Review"}
                      </span>
                    </td>
                  </tr>
                  {open && (
                    <tr>
                      <td colSpan={6} className="px-3 pb-4 pt-1">
                        <CalcDetail e={e} advanced={advanced} onCite={onCite} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
          <tfoot>
            <tr className="border-t-2 border-slate-200 bg-slate-50 font-semibold">
              <td className="px-3 py-2" colSpan={4}>
                Total claim ({pct(result.support_rate)} support rate)
              </td>
              <td className="px-3 py-2 text-ink">{money(result.total_claim_a)}</td>
              <td className="px-3 py-2" />
            </tr>
          </tfoot>
        </table>
      </div>

      {/* internal cross-check (Method B) */}
      {varianceRows.length > 0 && (
        <div className="mt-4">
          <button
            onClick={() => setShowVariance((s) => !s)}
            className="flex items-center gap-1.5 text-sm font-semibold text-slate-500 hover:text-slate-700"
          >
            <Chevron className={"transition-transform " + (showVariance ? "rotate-90" : "")} width={15} height={15} />
            Why is there a second "internal" figure? (cross-check)
          </button>
          {showVariance && (
            <div className="mt-2 animate-fade-in">
              <p className="mb-2 text-[13px] text-slate-500">
                <strong>Method A</strong> is EDB's official method — the number we submit.{" "}
                <strong>Method B</strong> is your team's internal hours-ratio calculation, run as a
                second opinion. Differences are flagged, never hidden. You only ever submit Method A.
              </p>
              <div className="overflow-hidden rounded-xl border border-slate-200">
                <table className="w-full text-left text-[13px]">
                  <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                    <tr>
                      <th className="px-3 py-2">Name</th>
                      <th className="px-3 py-2">EDB (A)</th>
                      <th className="px-3 py-2">Internal (B)</th>
                      <th className="px-3 py-2">Difference</th>
                      <th className="px-3 py-2">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {varianceRows.map((r, i) => (
                      <tr key={i}>
                        <td className="px-3 py-2 text-slate-600">{nameById.get(r.employee_id) || r.employee_id}</td>
                        <td className="px-3 py-2">{money(r.amount_a)}</td>
                        <td className="px-3 py-2">{money(r.amount_b)}</td>
                        <td className="px-3 py-2">{money(r.delta_abs)}</td>
                        <td className="px-3 py-2 text-slate-500">
                          {r.new_hire_flag ? "Verify (New Hire)" : r.material ? "Differs" : "Consistent"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ----------------------------------------------------- Grant & compliance */
function bigMoney(x: number): string {
  if (x >= 1_000_000) return "$" + (x / 1_000_000).toFixed(x % 1_000_000 === 0 ? 0 : 1) + "m";
  return money(x);
}

function GrantCompliance({ result }: { result: AnalysisResult }) {
  const g = result.grant;
  const dotCls = (s: string) =>
    s === "ok" ? "bg-emerald-500" : s === "attention" ? "bg-amber-500" : "bg-slate-300";
  return (
    <div className="space-y-5">
      <p className="text-sm text-slate-500">
        How this submission sits against the EDB Support Package's grant ceiling and disbursement
        gate, plus the audit &amp; reporting obligations.
      </p>

      {/* grant ceiling + disbursement */}
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="card p-4">
          <div className="text-xs font-medium text-slate-400">Maximum grant (manpower only)</div>
          <div className="mt-1 text-2xl font-bold text-ink">{bigMoney(g.max_grant_amount)}</div>
          <div className="mt-1 text-xs text-slate-400">
            This claim {bigMoney(g.total_claim)} · {(g.pct_of_grant * 100).toFixed(2)}% of grant
          </div>
        </div>
        <div className="card p-4">
          <div className="text-xs font-medium text-slate-400">
            Disbursable pre-completion ({pct(g.disbursement_threshold_pct)})
          </div>
          <div className="mt-1 text-2xl font-bold text-ink">{bigMoney(g.pre_completion_cap)}</div>
          <div className="mt-1 text-xs text-slate-400">
            {g.this_claim_fully_disbursable ? "This claim is fully disbursable now." : "Exceeds the pre-completion cap."}
          </div>
        </div>
        <div className="card p-4">
          <div className="text-xs font-medium text-slate-400">Held back until completion (30%)</div>
          <div className="mt-1 text-2xl font-bold text-ink">{bigMoney(g.post_completion_holdback)}</div>
          <div className="mt-1 text-xs text-slate-400">Released on project completion + all T&amp;Cs met.</div>
        </div>
      </div>

      {/* status banners */}
      {!g.within_grant && (
        <div className="flex items-center gap-2 rounded-xl bg-red-50 px-4 py-3 text-sm font-medium text-red-700">
          <Alert width={18} height={18} /> This submission exceeds the S$42m manpower grant ceiling.
        </div>
      )}

      {/* compliance checklist */}
      <div className="card overflow-hidden">
        <div className="border-b border-slate-100 px-5 py-3 text-sm font-semibold text-ink">
          Audit &amp; reporting obligations
        </div>
        <ul className="divide-y divide-slate-100">
          {result.compliance.map((o) => (
            <li key={o.key} className="flex items-start gap-3 px-5 py-3">
              <span className={"mt-1.5 h-2 w-2 shrink-0 rounded-full " + dotCls(o.status)} />
              <div className="flex-1">
                <div className="text-sm font-medium text-slate-700">{o.title}</div>
                <div className="text-[13px] text-slate-500">{o.detail}</div>
              </div>
              {o.due && (
                <div className="whitespace-nowrap text-right text-xs">
                  <div className="text-slate-400">due</div>
                  <div className="font-semibold text-slate-600">{prettyDate(o.due)}</div>
                </div>
              )}
            </li>
          ))}
        </ul>
      </div>
      <p className="text-xs text-slate-400">
        Support rate {pct(result.support_rate)} (confirmed). Claim window spans {result.claim_months} month(s);
        each claim must cover at least {result.min_claim_months}.
      </p>
    </div>
  );
}

/* --------------------------------------------------------------------- Pack */
function Pack({ result }: { result: AnalysisResult }) {
  const [files, setFiles] = useState<string[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    listDownloads(result.session).then(setFiles).catch((e) => setErr(String(e.message || e)));
  }, [result.session]);

  const edb = (files || []).filter((f) => f.startsWith("EDB_Submission"));
  const soe = (files || []).find((f) => f.startsWith("Statement"));
  const issues = (files || []).find((f) => f.startsWith("Issues"));

  const Card = ({ n, title, who, desc, children }: any) => (
    <div className="card p-5">
      <div className="text-xs font-semibold uppercase tracking-wide text-edb-600">
        {n} · for {who}
      </div>
      <div className="mt-1 font-semibold text-ink">{title}</div>
      <p className="mt-1 text-[13px] text-slate-500">{desc}</p>
      <div className="mt-3 flex flex-wrap gap-2">{children}</div>
    </div>
  );

  const DL = ({ f }: { f: string }) => (
    <a className="btn-outline" href={downloadUrl(result.session, f)} download>
      <Download width={16} height={16} /> {f}
    </a>
  );

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-500">
        Three documents, each for a different reader — generated from the figures you just reviewed.
      </p>
      {err && <div className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">{err}</div>}
      {!files && !err && <div className="text-sm text-slate-400">Preparing your documents…</div>}
      {files && (
        <>
          <Card
            n="1"
            who="EDB"
            title="EDB submission template"
            desc="The official RIS(C) export, filled with your qualifying staff (one file per company). Claim formulas and totals are preserved."
          >
            {edb.length ? edb.map((f) => <DL key={f} f={f} />) : (
              <span className="text-sm text-slate-400">No qualifying staff yet — resolve the issues first.</span>
            )}
          </Card>
          <Card
            n="2"
            who="the public accountant"
            title="Statement of Expenditure (SOE)"
            desc="The audit pack (SSRS 4400): expenditure summary, month-by-month workings, the evidence trail, the internal cross-check, and excluded staff with reasons."
          >
            {soe && <DL f={soe} />}
          </Card>
          <Card
            n="3"
            who="HR"
            title="Issues to fix"
            desc="Everyone not yet claimed, colour-coded: amber = fixable (document missing), red = not eligible, each with what to do."
          >
            {issues && <DL f={issues} />}
          </Card>
        </>
      )}
      {!result.support_rate_is_final && (
        <p className="flex items-center gap-1.5 text-xs text-slate-400">
          <Doc width={14} height={14} /> Files are marked non-final until EDB confirms the support rate.
        </p>
      )}
      <p className="text-xs text-slate-400">Claim period {prettyDate(result.claim_period[0])} – {prettyDate(result.claim_period[1])}.</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// The guided workflow that unwinds the pipeline one stage at a time.
// ---------------------------------------------------------------------------
const STEPS = [
  { key: "docs", label: "Document check", hint: "FR-2 — what's on file, what's missing" },
  { key: "eligibility", label: "Eligibility", hint: "FR-6 — who can be claimed, and why not" },
  { key: "claim", label: "Claim amount", hint: "FR-4 — EDB pro-ration, traced to source" },
  { key: "grant", label: "Grant & compliance", hint: "ceiling, disbursement gate, audit cadence" },
  { key: "pack", label: "Submission pack", hint: "FR-5/FR-7 — EDB template, SOE, issues list" },
] as const;

function Stepper({ step, furthest, onGo }: {
  step: number; furthest: number; onGo: (i: number) => void;
}) {
  return (
    <ol className="flex flex-wrap items-center gap-x-1 gap-y-2">
      {STEPS.map((s, i) => {
        const done = i < step;
        const here = i === step;
        const reachable = i <= furthest;
        return (
          <Fragment key={s.key}>
            {i > 0 && <span className="h-px w-4 bg-slate-300" aria-hidden />}
            <li>
              <button
                disabled={!reachable}
                onClick={() => onGo(i)}
                title={s.hint}
                className={
                  "flex items-center gap-2 rounded-full px-3 py-1.5 text-[13px] font-semibold transition-colors " +
                  (here
                    ? "bg-ink text-white"
                    : reachable
                      ? "text-slate-600 hover:bg-slate-100"
                      : "cursor-not-allowed text-slate-300")
                }
              >
                <span
                  className={
                    "flex h-5 w-5 items-center justify-center rounded-full text-[11px] " +
                    (here ? "bg-white/20" : done ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-400")
                  }
                >
                  {done ? <Check width={12} height={12} /> : i + 1}
                </span>
                {s.label}
              </button>
            </li>
          </Fragment>
        );
      })}
    </ol>
  );
}

/**
 * The results workflow: Document check → Eligibility → Claim amount → Grant &
 * compliance → Submission pack, with a step indicator and Back/Continue.
 *
 * The document check is a **strict gate**: while a BLOCKER document is missing,
 * Continue stays disabled until HR either re-uploads it or explicitly accepts
 * that those people are left out of this claim. That choice is the audit-clean
 * one — the affected staff are still reported (never silently dropped), they are
 * simply not claimed.
 */
export default function Results({
  result,
  advanced,
  onCite,
  onReupload,
}: {
  result: AnalysisResult;
  advanced: boolean;
  onCite: (c: Cite) => void;
  onReupload: (files: File[]) => void;
}) {
  const [step, setStep] = useState(0);
  const [furthest, setFurthest] = useState(0);
  const [acknowledged, setAcknowledged] = useState(false);

  const blockers = result.entities.flatMap((e) =>
    e.cells.filter(
      (c) => c.status === "missing" && c.severity === "BLOCKER" && !CONDITION_DOCS.has(c.doc_type)
    )
  );
  // A fresh analysis (new session) means new documents — re-arm the gate.
  useEffect(() => {
    setAcknowledged(false);
    setStep(0);
    setFurthest(0);
  }, [result.session]);

  const gated = step === 0 && blockers.length > 0 && !acknowledged;
  const go = (i: number) => {
    const next = Math.max(0, Math.min(STEPS.length - 1, i));
    setStep(next);
    setFurthest((f) => Math.max(f, next));
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <div className="mx-auto max-w-6xl px-4 pb-16 pt-6 sm:px-6">
      <ResultsSummary result={result} />

      <div className="mt-6 border-y border-slate-200 py-3">
        <Stepper step={step} furthest={furthest} onGo={go} />
      </div>

      <div className="mt-6">
        {step === 0 && <DocCheck result={result} onCite={onCite} onReupload={onReupload} />}
        {step === 1 && <Eligibility result={result} />}
        {step === 2 && <Claim result={result} advanced={advanced} onCite={onCite} />}
        {step === 3 && <GrantCompliance result={result} />}
        {step === 4 && <Pack result={result} />}
      </div>

      {gated && (
        <div className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-4">
          <div className="flex items-center gap-2 text-sm font-bold text-amber-800">
            <Alert width={18} height={18} />
            {blockers.length} required document(s) still missing
          </div>
          <p className="mt-1 text-[13px] text-amber-800/90">
            Upload the missing documents above to claim these people. If you continue without them,
            they are <b>excluded from this claim</b> and listed in the issues report — they are never
            silently dropped.
          </p>
          <label className="mt-3 flex items-center gap-2 text-[13px] font-medium text-amber-900">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
              className="h-4 w-4 rounded border-amber-400"
            />
            I understand — continue without these documents.
          </label>
        </div>
      )}

      <div className="mt-6 flex items-center justify-between">
        <button className="btn-ghost" disabled={step === 0} onClick={() => go(step - 1)}>
          <Chevron width={16} height={16} className="rotate-180" /> Back
        </button>
        <span className="text-xs text-slate-400">
          Step {step + 1} of {STEPS.length} · {STEPS[step].hint}
        </span>
        <button
          className="btn-primary"
          disabled={gated || step === STEPS.length - 1}
          onClick={() => go(step + 1)}
        >
          Continue <Chevron width={16} height={16} />
        </button>
      </div>
    </div>
  );
}
