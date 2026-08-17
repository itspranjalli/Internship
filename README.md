# R&D Manpower Grant Claim Automation

`edb_claim` automates the preparation of research-manpower grant claims for the AI Centre of
Excellence of a large Singapore engineering group, under a national R&D grant scheme
administered by a government agency. It takes the HR documents that arrive at the end of a
claim period and produces the three filed artefacts — the agency's official submission
template, a Statement of Expenditure for the external auditor, and an issues list for HR —
with every claimed figure traceable back to the source workbook cell it came from.

> **Note on naming.** This is an academic write-up of an internship project, so the sponsoring
> organisation, the funding agency and the scheme are referred to generically throughout this
> document, and no application reference is quoted in it. Code identifiers necessarily keep the
> original abbreviation — the package is `edb_claim`, the environment variables are `EDB_*` —
> because they are the literal API surface a reader has to type; the same is true of entity
> names inside `edb_claim/config.py` and the fixtures. All employee and salary data in this
> repository is synthetic.

The deterministic core (parsing, eligibility gates, Method A/B arithmetic, output writing)
computes **every** claim figure in pure Python. An isolated, optional local-LLM adapter only
proposes extractions and judgements for HR to confirm, and phrases answers in the assistant —
**it never computes an amount**. That boundary is enforced structurally: `calc/`, `validate/`
and `app/pipeline.py` import nothing from `edb_claim.llm`.

Status: working proof of concept, verified end-to-end on synthetic fixtures (see
[Verified results](#verified-results)). Outputs are pre-audit by construction.

---

## The problem

A single claim spans many participating legal entities across a three-year qualifying period.
Preparing one by hand means reconciling per-entity timesheet workbooks against a validated
researcher list and payroll, applying the scheme's eligibility rules (local citizens/PRs only,
basic monthly salary only, S$5,000 floor, S$20,000 monthly cap), and pro-rating salaries
across partial months of employment.

Two further constraints shape the design:

- **Two calculation methods disagree.** The agency's worked example pro-rates monthly; the
  internal `Staff Costs` sheet uses a single whole-span hours ratio. They do not produce the
  same number, and a ruling on which governs each edge case is still pending (PRD §10 Q1).
- **An external SSRS 4400 audit samples ≥ 85 % of claimed value.** Every sampled row must be
  defensible from source documents, so a figure without a traceable origin is a finding.

Automation has to hold both: it cannot quietly pick a method, and it cannot produce a number
it cannot explain.

---

## What it does

| Stage | Module | What happens |
|---|---|---|
| Ingest | `ingest/timesheet.py`, `ingest/rse_list.py`, `ingest/salary.py` | Parse the internal timesheet workbooks (`Time Sheet` from row 19, `Staff Costs` from row 15), the validated researcher list, and payroll. Every field carries an evidence reference (file / sheet / cell). |
| Completeness | `validate/completeness.py` | FR-2 missing-document check per person — what is on file, what is absent. |
| Eligibility | `validate/gates.py`, `validate/crosschecks.py`, `validate/verdict.py` | Gates G1–G5 (residency, researcher-list validation, salary floor, designation), cross-document reconciliation, and a single verdict per person with reasons. Exclusions are always reported, never silently dropped. |
| Calculation | `calc/method_a.py`, `calc/method_b.py` | Method A (the agency's monthly pro-ration — the submission basis) and Method B (internal hours-ratio replica, quirks intact). |
| Reconciliation | `calc/variance.py` | Per-person and aggregate A-vs-B variance, with the New-Hire `B > A` audit risk isolated regardless of magnitude. |
| Grant & compliance | `compliance.py` | S$42m manpower ceiling, the 70 % disbursement gate with 30 % holdback, and audit-cadence obligations. |
| Output | `output/edb_writer.py`, `output/soe.py`, `output/reports.py` | The agency's submission template (formulas, hidden mapping columns and totals preserved), the SOE audit pack, and HR's issues list. |
| Persistence | `db/store.py`, `db/schema.py` | Write-through to SQLite with idempotent UPSERTs, plus exact-SQL retrieval — the numeric path for the assistant. |

---

## Architecture

```
  React SPA (webui/)                    Streamlit shell (legacy)
          │                                       │
          ▼                                       │
  edb_claim/api/server.py                         │  calls run_pipeline directly
          │                                       │
          └──────────────►  app/pipeline.py  ◄────┘
                                 │      ← single orchestration seam
                                 │        (imports NO llm/ code)
   ┌──────────┬──────────────────┼──────────────────┬──────────┐
 ingest/   validate/           calc/         compliance.py   output/
                                 │
                              db/store.py  ──► edb_claim.db (SQLite)
                                 │
                                 ▼ read-only
                      llm/qa.py  +  eval/groundedness.py
                 (phrases retrieved facts; never produces a figure)
```

`app/pipeline.py` is the only orchestration module, and both front ends call `run_pipeline`
on it — the React app through the HTTP layer, Streamlit directly. It adds no
domain logic and computes no figure itself — it assembles inputs and groups per-employee
results. Input order is preserved throughout (employees in Time-Sheet order, entities in
upload order), so identical inputs yield byte-identical outputs, which the audit requires.

### Repository map

| Path | Contents |
|---|---|
| `edb_claim/` | The Python package (~9.7k LOC): `config.py` (all tunables), `ingest/`, `validate/`, `calc/`, `compliance.py`, `output/`, `db/`, `llm/`, `eval/`, `domain/`, `api/`, `app/` |
| `webui/` | React 18 + Vite + TypeScript + Tailwind front end; built into `webui/dist` and served by FastAPI |
| `tests/` | 15 pytest modules (~2.8k LOC) plus fixtures |
| `sample_data/` | Synthetic fixture generator and the generated workbooks — see `sample_data/README.md` for the PRD §8 case → employee map |
| `docs/` | The two authoritative Excel contracts (internal input checklist workbook, agency output template) and `docs/demo/` presentation material |

`edb_claim/evidence/` is an empty placeholder package — FR-7 evidence traceability is
implemented in `output/soe.py` and `validate/crosschecks.py`.

---

## Install

Requires Python 3.11 and Node with npm (developed against Python 3.11.14, Node 25 / npm 11;
`webui/package.json` declares no `engines` constraint).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

The front-end dependencies are installed automatically on first run; to do it up front:

```bash
npm --prefix webui install
```

## Run

The run scripts are not marked executable in git, so invoke them with `bash`:

```bash
bash run_web.sh                      # builds webui/, then serves on http://127.0.0.1:8010
```

| Variable | Effect |
|---|---|
| `PORT=8011` | Serve on another port (8010 is the default; 8000 is usually the local vLLM endpoint) |
| `SKIP_BUILD=1` | Skip the npm build when `webui/dist` is already current |
| `EDB_LLM_BASE_URL=""` | Force a pure offline run with no model endpoint |

On the landing page choose **explore with sample data** (or upload your own timesheet
workbooks, researcher list and payroll — everything is processed locally; salary data never leaves
the machine) and press **Analyse documents**. The UI then walks the pipeline one stage at a
time — **Document check → Eligibility → Claim amount → Grant & compliance → Submission
pack** — with a step indicator and Back/Continue navigation. The UI computes nothing itself.

**Document check is a hard gate.** If a required document is missing, *Continue* stays
disabled until you either re-upload it or explicitly acknowledge the gap, in which case the
affected people are excluded from the claim and listed with reasons. That keeps the
submission audit-clean rather than silently short.

To regenerate the synthetic fixtures and verify they round-trip through the ingest layer:

```bash
.venv/bin/python sample_data/generate.py           # rebuild
.venv/bin/python sample_data/generate.py --check   # rebuild, then verify via the T2/T3 ingest path
```

Note that `--check` *rewrites* the workbooks before verifying them, so it leaves
`sample_data/*.xlsx` and `tests/fixtures/*.xlsx` modified in git even when nothing has
changed semantically. Use `git checkout -- sample_data tests/fixtures` to discard that churn.

The Streamlit app (`bash run_app.sh`) is the original POC shell. It is superseded by the
React front end and kept only for reference.

## Test

```bash
.venv/bin/python -m pytest tests/ -q
```

**131 passed** (~11 s). The suite regenerates `tests/fixtures/*.xlsx` as it runs, so it
leaves those two workbooks modified in git afterwards — expected, and discardable with
`git checkout -- tests/fixtures`.

Coverage is deepest where the audit risk is: Method A, variance,
verdicts, ingest, outputs, the persistence store, groundedness and the LLM adapter.

Known gaps, stated rather than implied: there is no dedicated `test_method_b.py` (Method B is
exercised indirectly through `test_variance.py`), and no direct tests for
`validate/gates.py`, `validate/completeness.py`, `app/pipeline.py`, `api/server.py` or
`compliance.py`. `tests/_prove_offline_model.py` and `tests/_preview_ui_demo.py` are manual
scripts, deliberately not collected.

## The audit assistant

A **Grant & Verification Assistant** (`edb_claim/llm/qa.py`) is available on every screen: a
grounded, retrieval-augmented chatbot for the scheme and for this claim. Figure and
eligibility questions are answered from the pipeline rows by exact SQL lookup, never
generated; *"fetch the evidence for &lt;name&gt;"* returns the FR-7 source documents and
cells, which is what HR needs to answer a re-verification request from the agency.

It runs fully offline. Setting `EDB_LLM_BASE_URL` and `EDB_LLM_MODEL` connects a local
Qwen/vLLM endpoint for conversational phrasing (temperature 0, schema-constrained, cached) —
the model only phrases retrieved context and never emits a figure of its own.

Every answer is **verified before it is shown** (`edb_claim/eval/groundedness.py`, FR-14).
Each figure in a reply is checked against the figures the pipeline actually computed, the
stored rows for that person, the retrieved scheme facts and the config constants. The answer
then carries a *measured* `grounded` flag rather than an assumed one, rendered in the chat as
**✓ Figures verified** or **⚠ Unverified figure**. Nothing is ever discarded — an answer that
fails the check is still shown, annotated with a plain-language reason.

## Evaluate

```bash
.venv/bin/python -m edb_claim.eval          # offline
EDB_LLM_BASE_URL=http://localhost:8000/v1 \
EDB_LLM_MODEL=Qwen/Qwen3.6-35B-A3B \
  .venv/bin/python -m edb_claim.eval        # with a local model connected
```

The harness (`edb_claim/eval/`) scores the assistant against a question set keyed to the
PRD §8 synthetic cases — routing, the expected figure to the cent, and groundedness — and
writes `eval_report.json`. Expected values are derived by running the pipeline on
`sample_data/` at eval time, never hardcoded, so the question set cannot drift from the
fixtures.

Latest offline run: **`qa_groundedness` 33/33 (100 %)**, with **0/33 phrased by a model** —
the honest reading is that offline answers are grounded by construction, so this score
validates the retrieval and verification path, not a model. The report always prints that
count for exactly this reason.

Of the four scorers PRD FR-14 names, only `qa_groundedness` is implemented. `extraction`,
`designation` and `reconciliation` are registered as explicit `not_implemented` stubs, so
completing them is an addition rather than a refactor.

---

## Verified results

Measured on the shipped synthetic fixtures (20 employees across two entities, claim window
2026-01-01 → 2026-06-30, support rate 60 %):

| | |
|---|---|
| Fixture integrity | `generate.py --check` — all checks pass; 20 researchers, 111 person-months, 116 payroll records |
| Test suite | 131 passed |
| Eligibility outcome | 20 assessed → 14 qualify (2 of them flagged for review), 1 blocked, 5 excluded |
| Method A total (submission basis) | **S$492,934.55** |
| Method B total (internal cross-check) | S$48,271.63 |
| Groundedness eval | 33/33 |
| Documents produced | 4 workbooks — one submission template per entity (2), plus `Statement_of_Expenditure.xlsx` and `Issues_to_fix.xlsx` |

The two method totals are an order of magnitude apart (10.2×), and that is the finding, not a
bug — the two are not computed on the same basis. Method A sums a capped monthly figure
across the six claim months. Method B produces a *single* month-equivalent amount: the
`[B]` field is labelled "annual" in the internal sheet but evaluates to one capped **monthly**
salary, scaled by a whole-span hours ratio `[D3]` that is typically well below 1.

For a typical row the gap is therefore ≈ 6 ÷ `[D3]` — for ANS-001, `[D3]` = 0.494 and
6 ÷ 0.494 = 12.1, matching the observed A/B ratio of 34,200.00 / 2,817.24. Two of the twenty
fixture rows sit outside that pattern by design, and they are the interesting ones:

- **ANS-005** — a New Hire with no Method A months at all: A = 0.00 while B = 3,900.00,
  because Method B forces `[D3] = 100 %` with no timesheet evidence. This is the headline
  SSRS 4400 sampling risk, and the variance report isolates it regardless of magnitude.
- **DSG-001** — a below-floor row where `[B]` returns `"N/A"`, so B = 0.00 against
  A = 17,280.00.

The system surfaces these per person and in aggregate rather than reconciling them, because
the `[B]` labelling and New-Hire quirks are among the discrepancies awaiting a ruling from the
agency. Note the 10.2× aggregate ratio covers only the 14 qualifying employees, so it is not
simply 6 ÷ mean(`[D3]`).

> **Method A vs Method B.** Method A is the agency's monthly pro-ration — the number
> submitted. Method B is the internal hours-ratio method, run as a background *second opinion*
> that flags data anomalies (for example a New Hire with no timesheet, where Method B forces
> 100 % time and claims an amount Method A cannot evidence) before the auditor sees them. A
> ruling on which governs every edge case is pending (PRD §10 Q1), so both are kept and
> differences are surfaced, never silently resolved.

---

## Design decisions

- **Arithmetic is deterministic Python; the LLM is advisory only.** A claim figure produced
  by a language model cannot be defended in an SSRS 4400 sample. The boundary is enforced by
  import structure, not by convention.
- **Both calculation methods are retained.** They genuinely disagree and the authoritative
  ruling is pending, so resolving the conflict in code would be inventing a decision the
  project is not entitled to make.
- **Internal quirks are replicated, then flagged.** Method B's New-Hire auto-100 % time and
  its `[B]` field labelled "annual" while computing monthly are reproduced exactly and
  reported in the variance output, because "fixing" them would silently diverge from the
  workbook HR and the auditor both hold.
- **Everything runs locally.** Inputs are salary records, so there are no external API calls
  on claim data; the LLM endpoint is a local vLLM server and the store is a single SQLite
  file.
- **Determinism is a requirement, not a nicety.** Stable input ordering and idempotent UPSERT
  writes mean a re-run reproduces the submission exactly — necessary when an auditor
  re-derives a figure months later.
- **Low-confidence output is surfaced, never discarded.** Anything below the confidence
  threshold is shown to HR with a plain-language reason, so the system is never a black box.
- **The LLM layer is provider-agnostic.** It speaks an OpenAI-compatible interface, so the
  deployment target can change without touching the pipeline, and the pipeline runs fully
  with no model configured at all.
- **Source-document discrepancies are escalated, not resolved.** Where the PRD and the
  workbook conflict on the participating-entity count, the code follows the workbook and
  documents the conflict in place (`edb_claim/config.py`).

## Known limitations

- **Narrative retrieval is keyword-based, not vector-based.** The numeric path (exact SQL in
  `db/store.py`) is complete. The vector path is a schema-level stub: `sqlite-vec` tables and
  the `embedding_model` setting exist, but chunking and embedding (task T23) are unfinished,
  so narrative retrieval currently uses stemmed keyword token-overlap over a curated scheme
  knowledge base in `llm/qa.py`. `EDB_EMBEDDING_MODEL` is therefore a declared but unused
  knob today.
- **Three of four FR-14 scorers are unimplemented** (`extraction`, `designation`,
  `reconciliation`) — registered as explicit stubs.
- **Entity count is unresolved upstream.** The PRD specifies 17 participating entities; the
  source workbook maps one entity to three centre codes, giving 18. The code follows the workbook
  and flags the contradiction (`edb_claim/config.py`) rather than dropping a centre to force
  the expected total.
- **Several scheme parameters remain assumptions** pending the Letter of Award or auditor
  confirmation — the 9-month upskilling cap anchor, no public-holiday adjustment to working
  days, the claim window, and the 0.85 confidence-surfacing threshold. Each is marked
  `ASSUMED` in `edb_claim/config.py` and is env-overridable.
- **All outputs are pre-audit.** `claim_is_audited` is always false; the external Practitioner
  audits outside this system.
- **Fixtures are synthetic.** No real employee or salary data is in this repository.

## Configuration

`edb_claim/config.py` is the single source of every tunable — support rate, salary floor and
cap, working-time basis, claim and qualifying windows, grant ceiling, entity list, LLM and
persistence settings. The values that matter most are env-overridable:

| Variable | Default | Purpose |
|---|---|---|
| `EDB_SUPPORT_RATE` | `0.60` | Support rate (confirmed 60 % of capped basic monthly salary) |
| `EDB_LLM_BASE_URL` | unset in `config.py`; `run_web.sh`/`run_app.sh` default it to `http://localhost:8000/v1` | OpenAI-compatible endpoint; empty means offline/stub mode |
| `EDB_LLM_MODEL` | unset | Model name at that endpoint |
| `EDB_LLM_API_KEY` | placeholder | Ignored by local vLLM; required for a hosted provider |
| `EDB_DB_PATH` | `./edb_claim.db` | SQLite store location |
| `EDB_EMBEDDING_MODEL` | MiniLM-L6-v2 | Declared for the vector path; currently unused |

## Further reading

- `PRD.md` — requirements and the single source of truth (FR-1→FR-14, §6 dual-method spec,
  §8 test cases, §10 open questions).
- `PLAN.md` — target architecture and the T0–T24 task breakdown.
- `sample_data/README.md` — the PRD §8 case → fixture employee map.
- `docs/` — the two authoritative Excel contracts; `docs/demo/` — decks, screenshots and a
  recorded walkthrough.
