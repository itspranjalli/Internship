# PLAN.md — Implementation plan (EDB RIS(C) Grant Claim Automation POC)

Derived from `PRD.md` (the requirements source of truth) and `CLAUDE.md` (locked decisions). This file is the **build plan**: target architecture, the T0–T23 task breakdown, dependencies, and execution waves. One task ≈ one agent.

> Status: **building v1** — full pipeline end-to-end on synthetic data. The LLM is accessed via a **provider-agnostic OpenAI-compatible interface**; the deterministic pipeline runs without a live model (Qwen endpoint **deferred**), and Q&A *generation* activates when any model is connected. Shared working dir (not a git repo).

---

## 1. Target architecture

Deterministic core, thin Streamlit shell, isolated LLM adapter. Hard boundary: **the LLM proposes, deterministic Python disposes** — nothing in `calc/` or `output/` may import `llm/`.

```
edb_claim/
  config.py              support_rate (0.30, non-final), caps (5000/20000), 8.8 hrs/day,
                         claim window (Q7 default), entity list + 16→17 map, vLLM base_url/model,
                         confidence cutoff (0.85), embedding model. Single source of tunables.
  domain/
    models.py            Employee, PersonMonth, SalaryRecord, GateResult, Verdict,
                         MethodAResult, MethodBResult, VarianceRow, EvidenceRef
    calendar_utils.py    weekdays_in_month, worked_weekdays (partial), NETWORKDAYS replica
  ingest/                read-only parsers (openpyxl/pandas) → domain models + cell refs
    timesheet.py         Time Sheet (row 19+) + Staff Costs (row 15+)
    rse_list.py          ECMF-validated RSE list + citizenship
    salary.py            payslip / payroll register (deterministic xlsx path)
  validate/
    gates.py             G1–G7 per person-month → GateResult + source refs
    crosschecks.py       ECMF flag vs list, hours ≤ cap, payslip vs [A], dates vs coverage
    completeness.py      employee × month × doc matrix → blocker/warning (FR-2 severity table)
  calc/                  DETERMINISTIC ONLY — no llm/ import
    method_a.py          EDB monthly pro-ration (matches worked example to the cent)
    method_b.py          internal Staff Costs replica incl. quirks (replicate, do not fix)
    variance.py          per-employee Δ$/Δ%, aggregate, New-Hire isolation flags
  output/
    edb_writer.py        fill Details + Manpower_Locals (row 5+); preserve I/K/L formulas,
                         hidden col K, validations, row-2 totals
    reports.py           validation / verdict / variance render
  evidence/
    index.py             every figure → {file, sheet, cell/row}; per-employee evidence pack
  db/                    FR-13 persistence + retrieval (SQLite + sqlite-vec, single file)
    schema.py            entity, employee, document, doc_link, person_month, gate_result,
                         verdict, calc_result, evidence_ref, llm_log, run_manifest, chunk, chunk_vec
    store.py             write-through from ingest/calc/evidence; exact-SQL retrieval
    embed.py             chunking + local sentence-transformer embeddings → chunk_vec
  llm/                   ISOLATED adapter; degrades gracefully if endpoint down
    client.py            openai client → vLLM; temp 0, JSON-schema, retry
    cache.py             hash(prompt+model+schema) → persisted prompt/raw/ref (= llm_log)
    extract.py           FR-9 payslip/CPF/bank → JSON + confidence + location
    designation.py       FR-10 G5 judging + justification; borderline → review queue
    reconcile.py         FR-11 cross-doc matching (exact-ID auto, fuzzy → HR queue)
    qa.py                FR-12 two-path router: numeric→SQL, narrative→vector
  app/                   Streamlit: Upload → DocCheck → Calculate → Verdicts → Export
  manifest.py            run manifest → run_manifest table

sample_data/             synthetic generator + fixtures (PRD §8 deliberate cases)
tests/                   unit + golden-file tests incl. the 7,310.87 control
```

**Data flow:** Upload (FR-1) → ingest → completeness (FR-2) + gates/crosschecks (FR-3) → Method A & B (FR-4) → variance → verdicts (FR-6) → `edb_writer` fills template for QUALIFIES rows (FR-5) → evidence index links every figure (FR-7) → persisted to the DB (FR-13) → manifest. LLM (FR-9→12) feeds *proposals* into ingest/validate; the calc layer never touches it.

**Cent-level oracle:** `Salary Pro-ration E.g.` sheet — 9500 over 15 Jan–31 Mar 2018, 13/23 partial month, 30% → **$7,310.87**. This is the Method A golden test.

---

## 2. Task breakdown (one agent per task)

Format: id · goal · FRs/§ · deps · needs live Qwen?

| id | goal | covers | deps | live Qwen |
|---|---|---|---|---|
| **T0** | scaffold + config (all locked tunables) | §9 | — | no |
| **T1** | domain models + calendar utils (weekday/partial/NETWORKDAYS) | §6 | T0 | no |
| **T2** | internal-workbook ingest (Time Sheet 19+, Staff Costs 15+) w/ cell refs | FR-1, §4 | T1 | no |
| **T3** | RSE list + payslip/salary ingest (deterministic fallback path) | FR-1, §4 | T1 | no |
| **T4** | doc completeness matrix (FR-2 severity table) | FR-2 | T2,T3 | no |
| **T5** | eligibility gates G1–G7 + cross-checks; exclusions reported, never dropped | FR-3 | T2,T3 | no |
| **T6** | Method A engine (HIGH RISK — must hit 7,310.87) | FR-4 | T1,T5 | no |
| **T7** | Method B engine (HIGH RISK — replicate quirks, don't fix) | FR-4 | T1,T2 | no |
| **T8** | variance report (HIGHEST RISK — flag New-Hire B>A, surface §6 discrepancies) | FR-4 | T6,T7 | no |
| **T9** | verdict engine (QUALIFIES/EXCLUDED/BLOCKED + failed gates) | FR-6 | T4,T5 | no |
| **T10** | EDB output writer (HIGH RISK — preserve I/K/L, hidden K, validations, totals) | FR-5 | T6,T9 | no |
| **T11** | evidence traceability index → evidence_ref | FR-7 | T2,T3,T5,T6 | no |
| **T12** | reports (validation/verdict/variance render) | FR-3/4/6 | T5,T8,T9,T11 | no |
| **T13** | run manifest + determinism harness (tests cache-replay, not raw GPU) | §9 | T6,T7,T10 | no |
| **T14** | synthetic data generator — all 13 §8 cases, Q7 window | §8 | T1,T2 | no |
| **T15** | LLM client + cache (vLLM, temp0, schema, graceful-down) | §7,§9 | T0 | yes (deferred) |
| **T16** | FR-9 LLM document extraction (→ JSON + confidence + location) | FR-9 | T15,T3 | yes (deferred) |
| **T17** | FR-10 designation judging (G5; borderline → HR queue) | FR-10 | T15,T5 | yes (deferred) |
| **T18** | FR-11 cross-doc reconciliation (exact-ID auto, fuzzy → HR) | FR-11 | T15,T2,T3,T5 | yes (deferred) |
| **T19** | FR-12 audit Q&A — two-path router (numeric→SQL, narrative→vector) | FR-12 | T15,T22,T23,T11,T8 | yes (deferred) |
| **T20** | Streamlit app (LLM panels feature-flagged so core runs endpoint-down) | FR-8 | T4,T9,T10,T11,T12 | no (core) |
| **T21** | end-to-end acceptance tests (§11 DoD) | §11 | T8,T10,T11,T13,T14 | no |
| **T22** | FR-13 persistence layer (SQLite + sqlite-vec schema, write-through, exact-SQL retrieval) | FR-13 | T1 | no |
| **T23** | FR-13 chunking + embedding (local sentence-transformer → chunk_vec) | FR-13 | T22 | embeddings local (deferred only if vLLM route) |
| **T24** | evaluation harness + confidence-explanation layer: score LLM outputs vs §8 ground truth (extraction accuracy, designation P/R, match accuracy, Q&A groundedness); never discard — surface confidence + plain-language reason; record metrics per run | FR-14 | T14,T16,T17,T18,T19 | model when present |

---

## 3. Highest-risk tasks

1. **T8 variance (highest)** — the two methods genuinely disagree; ruling pending (Q1/Q3). Risk: an agent "fixing" Method B's New-Hire-100% or annual/monthly [B] quirk. Replicate-and-flag, never correct.
2. **T6 Method A** — 7,310.87 is the non-negotiable cent oracle; round only at column I, never pre-round qualifying cost.
3. **T10 EDB writer** — easiest place to silently break audit fidelity: clobbering I/K/L formulas, un-hiding col K, dropping validations, overwriting row-2 totals. Write only D/E/F/G/H value cells; round-trip fidelity test.
4. **T7 Method B** — use NETWORKDAYS×8.8 (not the header's C2−C1); reconcile Staff Costs cross-reference formulas.
5. **T15–T19 LLM** — blocked on the offline endpoint for live verify; risk of coupling into the calc path. Enforce the `calc/` ↛ `llm/` import boundary; ship deterministic fallback (T3) so the non-LLM pipeline passes T21 endpoint-down.

---

## 4. Execution waves (respect dependencies; parallel within a wave)

- **Wave 0 (serial):** T0 → T1
- **Wave 1 (parallel):** T2, T3, T14, T15, **T22**
- **Wave 2 (parallel):** T4, T5, then T6 ‖ T7
- **Wave 3:** T8 (after T6,T7), T9 (after T4,T5), T11 (after T2,T3,T5,T6), **T23** (after T22)
- **Wave 4:** T10, T12, T13
- **LLM track (parallel, deferred verify):** T16 ‖ T17 ‖ T18 after T15; T19 after T22+T23+T11+T8
- **Wave 5:** T20 → **T21** (last)

**Must serialize:** T6/T7 → T8 · T6+T9 → T10 · T22 → T23 → T19 · everything → T21.
**Hard parallel pairs:** T6 ‖ T7 · T16 ‖ T17 ‖ T18 · T2 ‖ T3 ‖ T15 ‖ T22.
