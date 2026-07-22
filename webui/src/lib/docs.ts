import type { AnalyzeInputs } from "../api";
import type { Supporting } from "../types";

// ---- document categorisation -----------------------------------------------
// The guided upload order is: EDB output template → trainee list → team
// timesheet → ECMF list → payroll, plus presence-checked "supporting" evidence.
export type Kind = "edb_template" | "trainee" | "timesheet" | "rse" | "payroll" | "supporting";

export const KIND_LABEL: Record<Kind, string> = {
  edb_template: "EDB output template",
  trainee: "Trainee list",
  timesheet: "Team timesheet",
  rse: "ECMF researcher list",
  payroll: "Payroll / payslips",
  supporting: "Supporting evidence",
};

export function guessKind(name: string): Kind {
  const n = name.toLowerCase();
  // 1) EDB output template (the export format HR provides first)
  if ((n.includes("edb") && n.includes("template")) || n.includes("output template")
      || n.includes("edb_output") || n.includes("edb output"))
    return "edb_template";
  // 2) trainee list (the roster docs are tracked against)
  if (n.includes("trainee")) return "trainee";
  if (n.includes("rse") || n.includes("ecmf") || n.includes("researcher")) return "rse";
  if (n.includes("payroll") || n.includes("payslip") || n.includes("salary")) return "payroll";
  // supporting evidence is presence-checked, not parsed — recognise it so a
  // leave report / CPF / progress report isn't treated as the core timesheet.
  if (Object.values(SUPPORTING_KEYWORDS).some((kws) => kws.some((kw) => n.includes(kw))))
    return "supporting";
  if (n.includes("timesheet") || n.includes("time sheet") || n.includes("time-sheet")
      || n.includes("internal") || n.includes("checklist") || n.includes("roster")
      || n.includes("coe") || n.includes("manpower"))
    return "timesheet";
  return "timesheet"; // the core HR workbook (default for an unrecognised name)
}

// ---- supporting-evidence checklist (auto-detected from file names) --------
export const SUPPORTING_FIELDS: { key: keyof Supporting; label: string; group: "company" | "person" }[] = [
  { key: "risc", label: "RISC submission form", group: "company" },
  { key: "loa", label: "EDB Letter of Award / offer letter", group: "company" },
  { key: "skill", label: "Skill validation list", group: "company" },
  { key: "trainee", label: "List of trainees (emp. no + dates)", group: "company" },
  { key: "artifacts", label: "Supporting AI artifacts (code / app)", group: "company" },
  { key: "leave", label: "Leave report", group: "company" },
  { key: "cpf", label: "CPF & bank statements (proof of payment)", group: "person" },
  { key: "pl3", label: "Formal PL3 status confirmation", group: "person" },
  { key: "cert", label: "Training certification (CLT / external)", group: "person" },
  { key: "progress", label: "Signed monthly progress reports", group: "person" },
  { key: "clocking", label: "Daily clocking records", group: "person" },
];

export const ALL_SUPPORTING_TRUE: Supporting = {
  risc: true, loa: true, skill: true, trainee: true, artifacts: true, leave: true,
  cpf: true, pl3: true, cert: true, progress: true, clocking: true,
};

const SUPPORTING_KEYWORDS: Record<keyof Supporting, string[]> = {
  risc: ["risc", "submission form"],
  loa: ["loa", "letter of award", "offer letter", "award"],
  skill: ["skill"],
  trainee: ["trainee", "training list"],
  artifacts: ["artifact", "codebase", "deliverable", "source code"],
  leave: ["leave"],
  cpf: ["cpf", "bank", "proof of payment"],
  pl3: ["pl3", "proficiency"],
  cert: ["cert", "clt"],
  progress: ["progress"],
  clocking: ["clocking", "attendance", "daily"],
};

export function detectSupporting(names: string[]): Supporting {
  const lower = names.map((n) => n.toLowerCase());
  const out = {} as Supporting;
  (Object.keys(SUPPORTING_KEYWORDS) as (keyof Supporting)[]).forEach((k) => {
    out[k] = lower.some((n) => SUPPORTING_KEYWORDS[k].some((kw) => n.includes(kw)));
  });
  return out;
}

// ---- merge newly-uploaded files into a prior submission (re-upload loop) --
export function mergeInputs(prev: AnalyzeInputs, added: File[]): AnalyzeInputs {
  const xlsx = added.filter((f) => f.name.toLowerCase().endsWith(".xlsx"));
  // timesheets & payroll: keep prior + new, de-duplicated by filename (new wins)
  const byName = new Map<string, File>();
  prev.timesheets.forEach((f) => byName.set(f.name, f));
  const payByName = new Map<string, File>();
  prev.payroll.forEach((f) => payByName.set(f.name, f));
  let rse = prev.rse;
  let edbTemplate = prev.edbTemplate;
  let trainee = prev.trainee;
  for (const f of xlsx) {
    const k = guessKind(f.name);
    if (k === "edb_template") edbTemplate = f;
    else if (k === "trainee") trainee = f;
    else if (k === "rse") rse = f;
    else if (k === "payroll") payByName.set(f.name, f);
    else if (k === "timesheet") byName.set(f.name, f); // replace same-name
    // "supporting" files are presence-only — never merged into core inputs
  }
  // supporting: OR-in any newly recognised docs, keep prior ticks
  const newlyDetected = detectSupporting(xlsx.map((f) => f.name));
  const supporting = { ...prev.supporting };
  (Object.keys(newlyDetected) as (keyof Supporting)[]).forEach((k) => {
    if (newlyDetected[k]) supporting[k] = true;
  });
  return {
    mode: "upload",
    edbTemplate,
    trainee,
    timesheets: Array.from(byName.values()),
    rse,
    payroll: Array.from(payByName.values()),
    supporting,
  };
}
