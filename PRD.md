# PRD — EDB RIS(C) Grant Claim Automation (AI COE POC)

| | |
|---|---|
| **Document status** | Draft v0.1 |
| **Date** | 05 Jun 2026 |
| **Author** | Pranjali Sonawane (AI COE), drafted with Claude |
| **Scheme** | Research Incentive Scheme for Companies — RIS(C) |
| **Application No** | S26-10249-RIS(C) |
| **Implementing company** | ST Engineering IHQ Pte. Ltd. |
| **Qualifying period** | 01-01-2026 → 31-12-2028 |
| **First claim ID** | S26-10249-RIS(C)_P0001 |

---

## 1. Problem statement

ST Engineering's AI Centre of Excellence claims manpower costs for qualifying AI Research Scientists & Engineers (RSEs) under EDB's RIS(C) scheme across **17 participating entities** (ST Engineering IHQ further split into GEC / GTO / IT centres). Today the claim preparation is fully manual:

- HR in each entity fills an internal **Claim Checklist & Timesheet** workbook monthly.
- Someone must reconcile timesheets against payslips, leave reports, CPF/bank statements per employee per month.
- Figures are re-keyed into the official **EDB Output Template** (RIS(C) v1.1 export format).
- An appointed auditor verifies the claim under **SSRS 4400** agreed-upon procedures, sampling **≥ 85 % of claimed value** — meaning nearly every claim row must have evidence retrievable on demand.

This is error-prone, slow, and audit risk concentrates in the weeks before submission. The POC automates ingestion → validation → calculation → EDB-format output → evidence traceability.


## 2. Goals & non-goals

### Goals (POC)

1. **Ingest** the documents HR already produces — no new data-entry burden.
2. **Flag missing / inconsistent documents** per employee per month, with a re-upload loop.
3. **Compute claims two ways, side-by-side** (see §6) — quantify the variance between the internal method and EDB's official pro-ration method, to support the pending methodology ruling.
4. **Generate the filled EDB Output Template** (Manpower_Locals etc.) ready for export.
5. **Per-trainee verdict**: for every person, a clear qualifies / does-not-qualify / blocked-pending-docs decision with reasons.
6. **One-click evidence traceability**: every claim row links back to its source documents (timesheet cell, payslip line, ECMF validation record) — directly servicing the ≥ 85 % audit sampling.

### Non-goals (POC)

- Equipment / Others cost categories of the EDB template (manpower only).
- `Manpower_Foreigners` claims (foreigners are non-qualifying for RSE headcount; they are *flagged*, not claimed).
- Integration with live HR/payroll systems (file upload only).
- Authentication / multi-tenant access control.
- Replacing the auditor's procedures — the tool prepares and evidences; it does not certify.

---

## 3. Users

**Single user: HR.** HR uploads the monthly documents per entity, resolves missing-document flags, reviews calculation results and per-trainee verdicts, and exports the filled EDB Output Template. The exported claims are verified downstream by the appointed public accountant using the SOE (Statement of Expenditure) under SSRS 4400 (≥ 85 % of claimed value sampled), then submitted to EDB — but those parties do not use the system itself.

---

## 4. Inputs

Per entity, per claim period:

**Core inputs (parsed — drive the calculation):**

| # | Document | Format | Purpose |
|---|---|---|---|
| 1 | Internal Claim Checklist & Timesheet workbook (`AI_COE_Claim_Checklist_Timesheet_for_FY_2026_to_2028_v2_Final.xlsx` layout) | xlsx | Project team roster, monthly hours, ECMF flag, no-other-grant confirmation, New Hire/Upskilled/Reskilled, AI proficiency & capability |
| 2 | Trainee / RSE list (ECMF-validated) | xlsx | Authoritative list of qualifying RSEs + citizenship/PR status |
| 3 | Payslips / payroll register | xlsx (POC); PDF later | Monthly **basic** salary evidence per employee per month |
| 4 | EDB Output Template (blank v1.1) | xlsx | Target output format |

**Supporting evidence (presence-checked only — linked, never parsed line-by-line in the POC):**

These are the wider set an HR officer assembles per UEN. Each is checked for *presence* and surfaced in the FR-2 matrix; severities are ASSUMED pending the auditor's confirmed list (§10 Q4). Scopes: *entity* = once per company; *person* = per claimable trainee.

| # | Document | Scope | Purpose / note |
|---|---|---|---|
| 5 | Completed RISC submission form | entity | Presence-checked (EDB approval already granted, so not a blocker for this claim) |
| 6 | EDB Letter of Award / offer letter | entity | Source of the confirmed support rate & holdback (until then 30 % ASSUMED, §6) |
| 7 | Skill validation list | entity | Evidence supporting designation/eligibility |
| 8 | List of trainees (employee no. + training start/end dates) | entity | Training-period roster, complements the RSE list |
| 9 | Supporting AI artifacts (codebase, app/system developed) | entity | Demonstrates the AI R&D deliverable |
| 10 | Leave report (medical / ICT / annual) | entity | Cross-reference for plausibility of hours (informational — template note 2 says hours are *not* adjusted for leave/PH) |
| 11 | CPF statement | person | Payment evidence |
| 12 | Bank statement | person | **Proof of payment** for SSRS 4400 |
| 13 | Formal PL3 status confirmation | person | Confirms proficiency level where claimed |
| 14 | Training certification with start/end dates | person | Where CLT / external training applies |
| 15 | Monthly progress report (signed by Training Supervisor) | person | Evidence of project involvement |
| 16 | Daily clocking record (actual days on AI COE project) | person | Supports the hours/days claimed |

**Internal workbook structure** (parsed by the system):
- `Time Sheet` — rows from 19: Employee ID, Name, Local/Foreigner, qualifications, designation, ECMF-validated (bool), no-other-grant (bool), PL1–PL5, AI capability, NH/Up/Re, monthly hours Jan–Dec, total.
- `Staff Costs` — rows from 15: actual monthly salary [A], qualifying salary `[B] = N/A if A<5000 else MIN(A, 20000)`, date join [C1], date left [C2], `[D1] = NETWORKDAYS(C1,C2) × 8.8`, project hours [D2], `[D3] = D2/D1` (**New Hire forced to 100 %**), `[E] = B × D3`.
- `Participating entities` — RSE counts per FY by NH/Reskilled/Upskilled, ECMF sign-off blocks.

---

## 5. Outputs

1. **Filled EDB Output Template** (xlsx, structure preserved):
   - `Details`: company, app no, claim ID, claim period, type (UnauditedClaim), final-claim flag, export timestamp.
   - `Manpower_Locals` (from row 5): (a) name, (b) qualifying category, (c) non-qualifying-designation confirmation, (d) monthly basic salary, (e/f) involvement period, (g) support level %, (h) qualifying cost $, (i) claim amount = g × h. *(The template's `I3` header label reads "= i × j" but the live formula is `=ROUND(G×H,2)`; do not "fix" column I to match the label.)*
2. **Validation report** — per entity: missing documents, inconsistencies, blockers vs warnings.
3. **Per-trainee verdict sheet** — qualifies / excluded / blocked + machine-readable reasons.
4. **Variance report** — internal method vs EDB method per employee and in total (input to the methodology ruling).
5. **Evidence pack index** — per claim row: source file + sheet/row/cell references for every figure used.

---

## 6. Calculation engine — dual method (DECIDED: implement both, side-by-side)

> **Open ruling.** The internal Staff Costs sheet and EDB's own pro-ration example disagree. Until EDB/auditor rules, the POC computes **both** and reports variance. The EDB method is the presumptive submission basis (it comes from EDB's own template); the internal method preserves reconciliation with HR's existing sheets.

### Common eligibility gates (apply to both methods)

A person-month is claimable only if **all** pass:

| Gate | Rule | Source |
|---|---|---|
| G1 | Local (SG citizen / PR) | Time Sheet col E + RSE list |
| G2 | ECMF-validated RSE | Time Sheet col H + ECMF list |
| G3 | Not enjoying another government cash grant | Time Sheet col I |
| G4 | Basic monthly salary ≥ S$5,000 | Payslip |
| G5 | Designation not in non-qualifying categories (Marketing, Finance, Sales, HR, Admin, Facilities Mgmt, Legal) | Time Sheet col G vs EDB template col (c) |
| G6 | Involvement period overlaps claim period | Staff Costs C1/C2 |
| G7 | Payslip evidence exists for the month | Document check |

Qualifying salary per month = `MIN(basic salary, 20000)`; **basic only** — no CPF, bonus, AWS, allowances, COLA, airfare. The two thresholds act in **different layers**: the **S$5,000 floor is exclusion gate G4** (person dropped, verdict EXCLUDED), while the **S$20,000 cap is an arithmetic clamp** applied per month to a *retained* person.

### Method A — EDB pro-ration (official example, presumptive)

For each employee, over `involvement ∩ claim period`:

```
qualifying cost = Σ over months m of:
    capped_salary(m) × month_fraction(m) × time_contribution(m)

month_fraction(m)      = 1 for full months;
                         worked_weekdays / total_weekdays(m) for partial months
time_contribution(m)   = MIN(1, hours(m) / (weekdays(m) × 8.8))
claim amount           = qualifying cost × support_rate
```

- Working days = weekdays (Mon–Fri); the EDB example (13/23 days, Jan 2018) and the internal sheet's NETWORKDAYS both exclude weekends only, not public holidays.
- `support_rate` = **30 % ASSUMED — must be confirmed from the Letter of Award** (configurable; output is blocked from "final" status until confirmed).
- **Rounding**: all arithmetic is carried at full precision; the *only* rounding is EDB's output formula `I = ROUND(G×H, 2)`. Internal figures (qualifying cost, `[E]`) are never pre-rounded — this prevents double-rounding drift against the hand-calc control (§11.3).

### Method B — Internal Staff Costs sheet (reconciliation)

Replicated exactly, including its quirks:

```
[B] = N/A if salary < 5000 else MIN(salary, 20000)
[D1] = NETWORKDAYS(date_join, date_left) × 8.8
[D3] = 100 % if New Hire else [D2 project hours] / [D1]
[E]  = [B] × [D3]
claim amount = [E] × support_rate
```

### Known discrepancies to surface in the variance report

1. **Basis**: monthly calendar pro-ration × monthly time % (A) vs single annual hours ratio (B).
2. **New Hire 100 %**: Method B grants 100 % time with no timesheet evidence — audit risk under SSRS 4400; Method A still requires monthly hours. The report flags every New Hire row where B > A.
3. **[B] semantics**: internal header says "annual" salary but the formula yields a monthly capped figure — replicated as-is, flagged in the report.

---

## 7. Functional requirements

### Local LLM intelligence layer (DECIDED)

The system uses a **locally hosted LLM** — **Qwen 3.6 35B A3B served via vLLM on the DGX** (OpenAI-compatible endpoint, base URL configurable) — so document understanding is genuinely intelligent rather than hard-coded parsing. This also satisfies the §9 data-residency requirement: salary data never leaves the machine, including for inference.

**Hard boundary — the LLM proposes, the deterministic engine disposes:**

- The LLM **never computes claim amounts**. All arithmetic (Methods A & B, caps, pro-ration) is pure Python — deterministic and auditable.
- LLM calls use temperature 0 with JSON-schema-constrained outputs; every extraction/judgement is **persisted with the prompt, raw response, and source-document reference**, so reruns replay the cached result (preserving the §9 determinism guarantee) and the auditor can inspect how any value entered the system.
- *Note on determinism*: temperature 0 maximizes answer stability but GPU inference is not bit-exact (batching / floating-point effects can occasionally vary a token) — the **cache-and-replay log is the actual determinism guarantee**, not the temperature setting. Temperature 0 does not reduce the model's capability; it only takes the model's single most probable answer instead of a randomized variation. (To be validated empirically during the POC.)
- Every LLM-extracted value is surfaced to HR for confirmation before it feeds a calculation; low-confidence extractions are flagged for manual entry (fallback path always exists).

The LLM powers FR-9 → FR-12 below.

### FR-1 Upload & claim setup
- Select entity (from the canonical 17-entity list) and claim period (start/end within qualifying period).
  - Note: the workbook `List` sheet enumerates **16** base UENs; IHQ splits into GEC/GTO/IT to yield the **17** participating entities. The app holds the canonical 17-entity list plus a 16→17 mapping from the `List` vocabulary.
  - POC default window = **01-01-2026 → 30-06-2026** (Q7), distinct from the §1 full qualifying period; G6 overlap and the §8 synthetic data target this window.
- Upload the core input document types (§4 #1–4); multiple files per type allowed.
- Confirm presence of the supporting-evidence checklist (§4 #5–16) — presence-checked only, not parsed; drives the FR-2 matrix.

### FR-2 Document completeness check
- Matrix view: employee × month × required document → present / missing / inconsistent.
- Missing items produce **blockers** (claim row suppressed) or **warnings** (claimable, flagged for audit) per a defined severity table.
- Re-upload loop: user fixes and re-uploads; checks re-run incrementally.

**Severity table** (ASSUMED — pending Q4 auditor doc list):

| Document / condition | Required scope | Severity | Basis |
|---|---|---|---|
| Payslip for the claimed month | per person-month | **BLOCKER** | G7 — no salary evidence → month not claimable |
| ECMF-validated RSE list | per entity (once) | **BLOCKER** | cannot run G2 without it |
| Internal Timesheet / Staff Costs workbook | per entity (once) | **BLOCKER** | primary roster/hours input |
| EDB blank output template | per entity (once) | **BLOCKER** | no output target |
| Leave report | per entity/period | WARNING | informational hours plausibility only (§4) |
| CPF statement | per person (presence) | WARNING | presence-checked, not parsed (§4) |
| Bank statement (proof of payment) | per person (presence) | WARNING | presence-checked; SSRS 4400 essential (§4 #12) |
| Timesheet hours > weekday capacity | per person-month | WARNING | cap clamp applied; flagged for audit |
| Payslip basic ≠ Staff Costs [A] | per person-month | WARNING | cross-check mismatch, surfaced for review |
| Completed RISC submission form | per entity (once) | WARNING | presence-checked; EDB approval already granted (§4 #5) |
| EDB Letter of Award / offer letter | per entity (once) | WARNING | confirms support rate/holdback; presence-checked (§4 #6) |
| Skill validation list | per entity (once) | WARNING | presence-checked (§4 #7) |
| List of trainees (emp. no + training dates) | per entity (once) | WARNING | presence-checked (§4 #8) |
| Supporting AI artifacts (codebase/app) | per entity (once) | WARNING | presence-checked (§4 #9) |
| Formal PL3 status confirmation | per person (presence) | WARNING | presence-checked (§4 #13) |
| Training certification (start/end dates) | per person (presence) | WARNING | presence-checked, CLT/external (§4 #14) |
| Monthly progress report (signed) | per person (presence) | WARNING | presence-checked (§4 #15) |
| Daily clocking record (actual days) | per person (presence) | WARNING | presence-checked (§4 #16) |

> The supporting-evidence rows are **presence-checked only** (never parsed) and **opt-in**: until HR indicates a document's presence it produces no matrix cell, so the baseline result is unchanged. Severities/scopes are ASSUMED pending the auditor's confirmed document list (§10 Q4).

### FR-3 Validation rules
- Eligibility gates G1–G7 per person-month.
- Cross-checks: timesheet ECMF flag vs ECMF list; timesheet hours ≤ weekdays × 8.8 (cap, per template note 1); salary on payslip vs Staff Costs [A]; join/left dates vs payslip coverage.
- Foreigners and non-qualifying designations are listed as **excluded with reason**, never silently dropped.

### FR-4 Calculation
- Methods A and B per §6, per employee, with full monthly breakdown retained (not just totals).
- Variance table: per-employee Δ$, Δ%, and aggregate; sortable; highlights New-Hire-driven gaps.

### FR-5 EDB output generation
- Fill `Details` + `Manpower_Locals` in a copy of the official template; formulas/validation in untouched columns preserved.
- Only verdict = QUALIFIES rows are written; the export manifest lists exclusions.

### FR-6 Per-trainee verdict
- One row per person: **QUALIFIES / EXCLUDED(reason) / BLOCKED(missing docs)** with every failed gate listed.

### FR-7 Evidence traceability
- Every figure in every claim row resolves to `{source file, sheet, cell/row}`.
- Per-employee "evidence pack" view: all source references for that claim row on one screen (one-click, per the audit requirement).

### FR-8 POC interface (DECIDED: web upload app)
- Streamlit app mirroring the real workflow: Upload → Doc check → Calculate → Verdicts → Export.
- The dashboard should be present to make it visually clear for the HR to proceed with the output otherwise the hr has the right to reject the claim

### FR-9 LLM document extraction
- Payslips, CPF and bank statements (xlsx in POC, PDF with varied layouts later) are parsed by the LLM into a fixed JSON schema: employee identifier, month, basic salary, allowances/bonus/CPF components (to *exclude*), payment reference.
- Each extracted field carries a confidence level (0–1 scale) and a pointer to its location in the source document. **Low-confidence responses are never discarded or hidden** — they enter the pipeline flagged and shown to HR alongside a **plain-language reason** for the low confidence (e.g. blurry field, multiple salary candidates, ambiguous designation), so HR is aware of every response and can confirm or override it. The 0.85 cutoff (ASSUMED, configurable) sets *when the explanation + confirm-prompt is surfaced*, not a discard threshold. See FR-14.

### FR-10 LLM designation judging (gate G5)
- Free-text designations from the Time Sheet are classified by the LLM against EDB's non-qualifying categories (Marketing, Finance, Sales, HR, Admin, Facilities Mgmt, Legal), with a one-line justification logged per judgement.
- Borderline calls (e.g. "Engineering Operations Manager") are flagged for HR review rather than auto-decided; clear passes/fails are pre-filled.

### FR-11 LLM cross-document reconciliation
- Employees are matched across Time Sheet / payroll / ECMF list despite name variants ("Tan Wei Ming" vs "WEI MING TAN"), differing ID formats, and typos; the LLM proposes match candidates with reasoning, HR confirms ambiguous ones.
- **Auto-accept rule (deterministic, ASSUMED):** exact Employee-ID match → auto-accepted; normalized-name-only or fuzzy/typo match → HR confirmation queue. The accept/queue decision is cached so reruns are identical (§9).
- Every validation flag and verdict gets a natural-language explanation grounded in the specific source values that triggered it (not generic error text).

### FR-12 Audit Q&A assistant
- Chat panel over the completed claim: "why is this row excluded?", "show the evidence for employee X's March figure", "which rows would change under Method B?".
- Answers are grounded strictly in the FR-13 store: numeric answers come from exact SQL on `calc_result`/`person_month` joined to `evidence_ref`; "show the evidence" / "why excluded" answers from vector retrieval over text chunks. The LLM cites `{doc, sheet, cell}` and never invents figures.

### FR-13 Persistence & retrieval store (DECIDED: SQLite + sqlite-vec, local)
- All parsed facts, gate results, verdicts, calc breakdowns, evidence refs and the LLM cache/replay log persist in a **single local SQLite file**; document-text embeddings (from a **local sentence-transformer by default**, switchable to the vLLM endpoint) live in the same file via **`sqlite-vec`**. No server; portable; deterministic (§9).
- **`employee_id` is the partition key**: every document, figure and text chunk is scoped to an employee — shared entity inputs (the timesheet workbook) are split into per-employee-row chunks via `doc_link` — so the chatbot retrieves one person's full document set on demand.
- **Two retrieval paths (audit-safety):** numeric/factual questions are answered by **exact SQL lookup** on the structured tables (never similarity); narrative/evidence questions by **metadata-filtered** (employee, month, doc_type) **vector search** over text chunks. The LLM may not emit any figure absent from a retrieved structured row — enforcing FR-12 "cites, never invents."
- **Schema (core):** `entity, employee, document, doc_link, person_month, gate_result, verdict, calc_result, evidence_ref, llm_log, run_manifest`; **vector:** `chunk, chunk_vec`. `evidence_ref` backs FR-7 one-click traceability; `llm_log` is the FR-9→12 cache-and-replay + audit trail.
- **Determinism:** embeddings and LLM calls cached; fixed top-k with stable tie-break; identical inputs → identical retrieval.

### FR-14 Response evaluation & confidence transparency (DECIDED)
- **No black box, nothing discarded.** Every LLM-derived response (FR-9 extraction, FR-10 designation, FR-11 match, FR-12 answer) is surfaced to HR with its confidence and, when below the cutoff, a **plain-language reason** for it — so HR sees and judges *every* response, not just the confident ones.
- **Evaluation harness** scores LLM outputs against the §8 synthetic ground truth: extraction field accuracy, designation classification (precision/recall on non-qualifying categories), reconciliation match accuracy, and Q&A **groundedness** (every figure in an answer must trace to a row in the FR-13 store — automated pass/fail). Deterministic calc is verified separately against hand-calc controls (e.g. 7,310.87).
- Metrics are recorded per run (manifest) and shown in the UI, so HR sees the quality basis before acting.
- **Model-agnostic:** the LLM is accessed through a provider-agnostic OpenAI-compatible interface; the deterministic pipeline runs fully without a live model, and Q&A *generation* activates when any model is connected (the Qwen endpoint is deferred — see CLAUDE.md).

---

## 8. Test data (DECIDED: synthetic)

A generator script produces a `sample_data/` set covering 2–3 entities, ~10 employees each, embedding deliberate cases:

| Case | Exercises |
|---|---|
| Standard full-period RSE | Happy path, both methods agree-ish |
| Mid-period joiner / leaver | Partial-month pro-ration (Method A) |
| Salary S$4,800 | G4 floor → excluded |
| Salary S$23,000 | S$20k cap |
| Foreigner | G1 exclusion |
| Not ECMF-validated | G2 exclusion |
| "Enjoying other grant" = true | G3 exclusion |
| Designation "HR Manager" | G5 exclusion |
| New Hire, no timesheet hours | Method A vs B divergence + audit flag |
| Missing payslip for one month | G7 blocker + re-upload loop demo |
| Timesheet hours > monthly capacity | Cap warning |
| Name variant across docs ("Tan Wei Ming" / "WEI MING TAN") | FR-11 LLM reconciliation + HR confirm |
| Ambiguous designation ("Engineering Operations Manager") | FR-10 borderline G5 judgement → HR review queue |

---

## 9. Non-functional requirements

- **Auditability**: deterministic — same inputs always produce identical outputs. Claim arithmetic is pure Python; LLM outputs are cached and replayed on rerun (temperature 0, schema-constrained), and every LLM call is logged with prompt + response + source reference. Every run logs an export manifest (inputs, hashes, parameters, model version, timestamp).
- **No data leaves the machine** (salary data is sensitive): fully local processing **including LLM inference** — Qwen 3.6 35B A3B on the DGX via vLLM; no external API calls on claim data.
- **Template fidelity**: output opens cleanly in Excel; EDB's own formulas (e.g. `I = ROUND(G×H,2)`, blacklist mapping columns K/L) remain intact.
- **Scale**: 17 entities × ~50 employees × 36 months without distress (well within xlsx/pandas limits); LLM throughput sized for batch extraction of one entity's monthly document set in minutes, not hours.
- **Stack**: Python 3, openpyxl, pandas, Streamlit (already provisioned in `.venv`); `openai` client pointed at the vLLM endpoint (base URL + model name configurable); **SQLite + `sqlite-vec`** for the local persistence/vector store (FR-13).

---

## 10. Open questions (blocking items tracked to closure)

| # | Question | Owner | Status |
|---|---|---|---|
| Q1 | Methodology ruling: EDB pro-ration vs internal hours method | EDB / auditor via HR | **Open** — POC ships both |
| Q2 | Exact support rate (assumed 30 %) | Letter of Award | **Open** — configurable. While `support_rate` = assumed 0.30, export is marked non-final via: `Details` claim-type `UnauditedClaim` + a non-final banner cell in `Details` + manifest `final=false`. |
| Q3 | New Hire auto-100 % time: acceptable without timesheets? | Auditor | **Open** — flagged in variance report |
| Q4 | Auditor's confirmed document list (May 2026) — any items beyond §4? | HR | **Open** |
| Q5 | Do public holidays reduce "working days"? (Template/EDB example say no — weekends only) | Auditor | Assumed **no**; confirm |
| Q6 | Relationship to older `~/Developer/Edb` project & its data vault | User | **Open** |
| Q7 | Claim period for P0001 (template shows start 01-01-2026, end blank) | HR | **Open** — POC default 01-01-2026 → 30-06-2026 |
| Q8 | Participating-entity count: PRD/CLAUDE say **17**, but the workbook splits IHQ into GEC/GTO/IT giving 16 base − IHQ + 3 = **18** | HR / EDB | **Open** — `config.py` ships 18 (workbook-faithful); confirm 17 vs 18 |

---

## 11. Success criteria (Definition of Done)

1. Upload the synthetic document set for one entity → all 13 error cases in §8 are caught and correctly classified.
2. Fix the "missing payslip" case via re-upload → blocker clears without re-doing anything else.
3. Export produces a `Manpower_Locals` sheet that matches a hand-calculated control for ≥ 3 employees to the cent (Method A).
4. Variance report quantifies Method A vs B difference and isolates the New-Hire effect.
5. For any claim row, the evidence pack resolves every figure to a source reference in one click.

---

## 12. Phasing

| Phase | Scope |
|---|---|
| **POC (this PRD)** | One-entity flow end-to-end, synthetic data, manpower-locals only |
| **Pilot** | 2–3 real entities with anonymized real data; auditor walkthrough of evidence packs |
| **Production-track** | All 17 entities, PDF payslip parsing, consolidation dashboard, role-based access, retention policy. *(The per-employee SQLite + sqlite-vec store is now built in the POC — FR-13; production-track scales it to all entities and adds retention.)* |

