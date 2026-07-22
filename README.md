# EDB RIS(C) Grant Claim Automation (AI COE POC)

`edb_claim` is a proof-of-concept pipeline that automates preparation of EDB
RIS(C) grant claims for ST Engineering's AI COE: HR document upload →
missing-doc validation → dual-method claim calculation → filled EDB output
template → per-row evidence traceability for the SSRS 4400 audit. The
deterministic core (parsing, gates, Method A/B arithmetic, output) computes
every claim figure in pure Python; an isolated, optional local-LLM adapter
only proposes extractions/judgements for HR to confirm — it never computes
amounts.

## Install

```bash
.venv/bin/pip install -r requirements.txt   # openpyxl already provisioned
```

## Run the POC app

```bash
.venv/bin/python sample_data/generate.py     # (re)build the synthetic fixtures
.venv/bin/streamlit run edb_claim/app/main.py
```

The portal is a clean, guided workflow that unwinds the backend one stage at a
time: **Documents → Document check (FR-2) → Eligibility (FR-6) → Claim amount
(FR-4) → Submission pack (FR-5/SOE/FR-7)**, with a step indicator and
Back/Continue navigation. From the landing page, keep **Use sample data** (or
upload your own timesheet workbook(s), ECMF list, and payroll — all processed
locally) and press **Analyse documents**. The UI computes nothing itself — every
figure comes from the deterministic pipeline (`edb_claim/app/pipeline.py`).

The **Document check** stage is a strict gate: if any required document is
missing, *Continue* is disabled until you either re-upload the documents or
explicitly acknowledge the gap (the affected people are then excluded from this
claim). This keeps the submission audit-clean.

A **Grant & Verification Assistant** (right-hand panel, `edb_claim/llm/qa.py`) is
available on every screen — a grounded, retrieval-augmented chatbot for the
RIS(C) scheme and this claim. Figure/eligibility questions are answered straight
from the pipeline rows (never invented); *"fetch the evidence for &lt;name&gt;"*
returns the FR-7 source documents and cells so HR can answer an EDB
re-verification request. It runs fully offline (answering from the claim data and
scheme knowledge base); set `EDB_LLM_BASE_URL` and `EDB_LLM_MODEL` to connect the
local Qwen/vLLM endpoint for conversational answers (temperature-0,
schema-constrained, cached — the model only phrases retrieved context, it never
emits a figure).

The **Submission pack** produces the three documents needed to file the claim
(`edb_claim/output/`):

- **EDB submission template** (`edb_writer.py`) — the official RIS(C) export,
  one per company, with the claim formulas / hidden columns / totals preserved.
- **Statement of Expenditure / SOE** (`soe.py`) — the public accountant's audit
  pack: expenditure summary, month-by-month workings, evidence trail
  (file/sheet/cell), the A-vs-B cross-check, and excluded staff with reasons.
- **Issues to fix** (`reports.py`) — HR's action list of anyone not yet claimed.

> **Method A vs Method B.** Method A is EDB's monthly pro-ration — the number we
> submit. Method B is the internal hours-ratio method, run as a background
> *second opinion* that flags data anomalies (e.g. a New Hire with no timesheet)
> before the auditor sees them. A ruling on which governs every edge case is
> pending from EDB (PRD §10 Q1), so both are kept and differences are surfaced,
> never silently resolved.

## Where to look

- `PRD.md` — requirements (single source of truth).
- `PLAN.md` — architecture and the T0–T24 task breakdown / execution waves.
- `CLAUDE.md` — locked decisions and domain rules that must not be violated.
- `edb_claim/config.py` — all tunables (support rate, salary caps, claim
  window, entity list, LLM/embedding/db settings).
