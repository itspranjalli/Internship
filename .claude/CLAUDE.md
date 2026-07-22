# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

POC to automate EDB RIS(C) grant claim preparation for ST Engineering's AI COE (App No S26-10249-RIS(C), qualifying period 01-01-2026 → 31-12-2028, 17 participating entities). Pipeline: HR document upload → missing-doc validation → claim calculation → filled EDB output template → per-claim-row evidence traceability for the SSRS 4400 audit (auditor samples ≥ 85 % of claimed value, verified via Statement of Expenditure).

## Where things are

- `PRD.md` — **what to build** (requirements, single source of truth). FR-1→FR-13, §6 dual-method spec, §8 test cases, §10 open questions, §11 Definition of Done.
- `PLAN.md` — **how to build it** (target architecture, the T0–T23 task breakdown, dependencies, execution waves). Read this before implementing; one task ≈ one agent.
- `docs/` — the input/output Excel contracts (read, don't guess layouts).
- `CLAUDE.md` (this file) — locked decisions and domain rules that override defaults.

## Current state: building v1 (full pipeline end-to-end)

Implementation of **v1 — full pipeline end-to-end on synthetic data** is underway per `PLAN.md` (tasks T0–T24). The LLM layer is **provider-agnostic** behind an OpenAI-compatible interface; the deterministic pipeline runs **without a live model** (Qwen endpoint **deferred for now**), and Q&A *generation* activates when any model is connected. Decisions already locked (do not re-ask):

- **Dual calculation engine**: Method A = EDB monthly pro-ration (presumptive submission basis) AND Method B = internal Staff Costs hours-ratio method (for reconciliation), with a variance report. The two methods genuinely disagree; a ruling from EDB/auditor is pending (PRD §10 Q1).
- **POC form**: Streamlit upload app, fully local (salary data — no external API calls on claim data).
- **Test data**: synthetic, with the deliberate error cases enumerated in PRD §8.
- **Local LLM layer**: Qwen 3.6 35B A3B served via vLLM on the user's DGX (OpenAI-compatible endpoint). Powers document extraction, G5 designation judging, cross-doc reconciliation, and an audit Q&A assistant (PRD FR-9 → FR-12). Hard boundary: **the LLM never computes claim amounts** — all arithmetic is deterministic Python; LLM calls are temperature-0, schema-constrained, cached, and logged.
- **Persistence**: per-employee **SQLite + sqlite-vec** store, built in the POC (PRD FR-13). Two-path retrieval — exact SQL for figures, vector search for narrative; the LLM never emits a figure not in a retrieved structured row. Embeddings from a local sentence-transformer by default.
- **Eval & transparency** (PRD FR-14): low-confidence LLM responses are **never discarded** — every response is surfaced to HR with its confidence and a plain-language reason when low, so the system is never a black box. An eval harness scores LLM outputs against §8 synthetic ground truth (incl. Q&A groundedness: every figure must trace to a stored row).

## Environment

- Python venv at `.venv/` with `openpyxl` (plus `streamlit`/`pandas` to be added when implementation starts). Not a git repo.
- Inspect the Excel templates with `.venv/bin/python` + openpyxl, `data_only=False` to see formulas.

## Source templates (`docs/`)

These two workbooks define the input and output contracts — read them, don't guess layouts:

- `EDB_Output Template.xlsx` — official RIS(C) v1.1 export format (the output to produce). Key sheets: `Details` (claim header), `Manpower_Locals` (data from row 5; col I formula `=ROUND(G*H,2)` and hidden mapping cols K/L must be preserved when writing), `Salary Pro-ration E.g.` (EDB's authoritative worked example of Method A).
- `AI_COE_Claim_Checklist_Timesheet_for_FY_2026_to_2028_v2_Final.xlsx` — internal workbook HR fills (the primary input). `Time Sheet` data rows start at 19; `Staff Costs` data rows start at 15 and cross-reference Time Sheet by formula; hidden `List` sheet holds the dropdown vocabularies (entities, PL1–PL5, AI capabilities, New Hire/Upskilled/Reskilled).

## Domain rules that must never be silently violated

- Qualifying salary = **basic monthly salary only** (no CPF/bonus/AWS/allowances), floor S$5,000, cap S$20,000/month.
- Only ECMF-validated, local (SG citizen/PR) RSEs are claimable; exclusions must be reported with reasons, never silently dropped.
- "Working days" = weekdays only (no public-holiday adjustment) at 8.8 hrs/day — consistent across the EDB example and internal NETWORKDAYS formulas.
- Support rate is **assumed 30 %** until confirmed from the Letter of Award; keep it configurable and mark outputs non-final.
- Internal Method B quirks (New Hire auto-100 % time; `[B]` labeled "annual" but computed monthly) are replicated **as-is** and flagged in the variance report — do not "fix" them.
- Determinism: same inputs must produce identical outputs (audit requirement).

## Timeline context

Per-UEN audits start early Oct 2026; group submission to EDB end Nov 2026. Open questions blocking finalization are tracked in PRD §10.
