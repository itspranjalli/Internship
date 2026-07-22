// Mirrors edb_claim/api/serialize.py — the JSON shape of one analysis run.

export interface Health {
  ok: boolean;
  llm_enabled: boolean;
  sample_available: boolean;
  support_rate: number;
  support_rate_is_final: boolean;
  claim_period: [string, string];
  application_no: string;
}

export interface EvidenceRef {
  file: string;
  sheet: string | null;
  cell: string | null;
  label: string | null;
}

export interface MatrixCell {
  employee_id: string | null;
  entity: string;
  doc_type: string;
  doc_label: string;
  scope: string;
  status: string;
  severity: string;
  month: number | null;
  reason: string;
  source: EvidenceRef | null;
}

export interface GateRow {
  code: string;
  name: string;
  passed: boolean;
  reason: string;
  needs_review: boolean;
}

export interface MonthRow {
  year: number;
  month: number;
  capped_salary: number;
  salary_capped: boolean;
  month_fraction: number;
  full_month: boolean;
  weekdays: number;
  worked_weekdays: number;
  time_contribution: number;
  time_clamped: boolean;
  capacity_hours: number;
  implied_hours: number | null;
  qualifying_cost: number;
  salary_source: EvidenceRef | null;
  hours_source: EvidenceRef | null;
}

export interface Employee {
  id: string;
  name: string;
  entity: string;
  designation: string;
  status: "QUALIFIES" | "EXCLUDED" | "BLOCKED";
  qualifies: boolean;
  needs_review: boolean;
  zero_claim: boolean;
  reasons: string[];
  monthly_basic_salary: number | null;
  claim_amount: number;
  qualifying_cost_total: number;
  support_rate: number;
  months_capped: number;
  crosscheck_ok: boolean;
  involvement_from: string | null;
  involvement_to: string | null;
  method_b: { claim_amount: number; new_hire: boolean } | null;
  gates: GateRow[];
  monthly: MonthRow[];
}

export interface VarianceRow {
  employee_id: string;
  amount_a: number;
  amount_b: number;
  delta_abs: number;
  material: boolean;
  new_hire_flag: boolean;
}

export interface Entity {
  entity: string;
  file: string;
  rollup: {
    employee_count: number;
    ready_count: number;
    blocked_count: number;
    blocker_count: number;
    warning_count: number;
    summary: string;
  };
  blockers: MatrixCell[];
  warnings: MatrixCell[];
  cells: MatrixCell[];
  employees: Employee[];
  variance: { total_a: number; total_b: number; total_delta_abs: number; rows: VarianceRow[] };
  ingest_warnings: string[];
}

export interface GrantSummary {
  max_grant_amount: number;
  manpower_only: boolean;
  total_claim: number;
  pct_of_grant: number;
  within_grant: boolean;
  disbursement_threshold_pct: number;
  pre_completion_cap: number;
  post_completion_holdback: number;
  this_claim_fully_disbursable: boolean;
}

export interface Obligation {
  key: string;
  title: string;
  detail: string;
  due: string | null;
  status: "ok" | "attention" | "info";
}

export interface AnalysisResult {
  session: string;
  support_rate: number;
  support_rate_is_final: boolean;
  claim_period: [string, string];
  total_claim_a: number;
  total_claim_b: number;
  grant: GrantSummary;
  compliance: Obligation[];
  claim_months: number;
  min_claim_months: number;
  errors: string[];
  counts: { total: number; qualify: number; blocked: number; excluded: number; needs_review: number };
  entities: Entity[];
  docs: { label: string; name: string }[];
}

export interface ProgressEvent {
  type: "progress";
  pct: number;
  label: string;
  detail: string;
}
export interface ResultEvent {
  type: "result";
  data: AnalysisResult;
}
export interface ErrorEvent {
  type: "error";
  message: string;
}
export type StreamEvent = ProgressEvent | ResultEvent | ErrorEvent;

// audit assistant
export interface ChatAnswer {
  text: string;
  citations: EvidenceRef[];
  offline: boolean;
  used_model: boolean;
  mode: string;
  confidence: number | null;
}
export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  citations?: EvidenceRef[];
  mode?: string;
}

// supporting-evidence checklist
export interface Supporting {
  risc: boolean;
  loa: boolean;
  skill: boolean;
  trainee: boolean;
  artifacts: boolean;
  leave: boolean;
  cpf: boolean;
  pl3: boolean;
  cert: boolean;
  progress: boolean;
  clocking: boolean;
}
