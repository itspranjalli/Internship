"""The slide spine — the single source of truth for both renderers.

Every number here was verified against the running system on 2026-08-10, not
copied from the PRD. Where a figure is dataset- or rate-dependent it carries the
tag inline, because four different claim totals are in circulation:

    $7,310.87    EDB's own published worked example        @ 30% (their rate)
    $492,934.55  sample_data/, 14 qualifying (13 non-zero) @ 60%
    $122,290.91  docs/demo/testkit/, 3 of 5 qualifying     @ 60%
    the per-employee figures in sample_data/README.md are STALE @ 30% — never quote them.

Slide kinds consumed by both renderers:
    title | bullets | table | code | diagram | stats | image | split | quote | closing
"""

# ---------------------------------------------------------------- constants
APP_NO = "S26-10249-RIS(C)"
QP = "01 Jan 2026 – 31 Dec 2028"
CLAIM_WINDOW = "01 Jan 2026 – 30 Jun 2026"

VERIFIED = {
    "tests": 131,
    "test_files": 15,
    "py_loc": 11911,
    "ts_loc": 2764,
    "test_loc": 2595,
    "support_rate": "60%",
    "total_claim": "$492,934.55",
    "qualifying": 14,
    "nonzero": 13,
    "blocked": 1,
    "excluded": 5,
    "roster": 20,
    "tables": 16,
    "evidence_rows": 312,
}


def S(kind, **kw):
    d = {"kind": kind}
    d.update(kw)
    return d


SLIDES = [

    # ---------------------------------------------------------------- 1
    S("title",
      eyebrow="EDB SUPPORT PACKAGE FOR AI COE  ·  RESEARCH INCENTIVE SCHEME RIS(C)",
      title="Grant claim preparation\nas a deterministic pipeline",
      subtitle="Architecture, calculation engines, LLM guardrails and evaluation",
      meta=f"Application No. {APP_NO}   |   Qualifying period {QP}   |   "
           f"ST Engineering AI Centre of Excellence",
      foot="Engineering deep-dive  ·  ST Engineering HR  ·  Confidential"),

    # ---------------------------------------------------------------- 2
    S("bullets",
      kicker="The problem",
      title="An audit requirement, not an arithmetic problem",
      items=[
          ("The arithmetic is easy.", "Monthly pro-ration of a capped salary. A spreadsheet "
           "does it. That is not what makes this hard."),
          ("The audit is the constraint.", "An ACRA-registered Practitioner performs SSRS 4400 "
           "agreed-upon procedures and samples at least 85% of claimed value against the "
           "Statement of Expenditure. Nearly every claim row must have its evidence "
           "retrievable on demand."),
          ("So evidence cannot be reconstructed at export.", "It has to be threaded from the "
           "parser forward. EvidenceRef{file, sheet, cell_or_row, label} is attached at the "
           "moment a value is read out of a workbook, and survives all the way to the pack."),
          ("Three workbook contracts, re-keyed by hand.", "An internal Checklist/Timesheet per "
           "entity per month, a payroll register, an ECMF-validated RSE list — reconciled "
           "into EDB's official RIS(C) v1.1 template."),
          ("Determinism is an audit property.", "The same inputs must produce byte-identical "
           "outputs, or a re-run during the audit window changes the answer."),
      ],
      note="Non-goals: equipment/other cost categories, Manpower_Foreigners claims "
           "(foreigners are flagged, never claimed), live HR/payroll integration, "
           "and replacing the auditor's procedures."),

    # ---------------------------------------------------------------- 3
    S("table",
      kicker="Configuration",
      title="Scheme rules are config, not code",
      intro="edb_claim/config.py is a frozen dataclass; domain rules are deliberately NOT "
            "env-overridable. Only 6 knobs read the environment. Every ASSUMED row is a "
            "decision waiting on EDB or the auditor — the code carries the open question "
            "rather than silently picking a side.",
      cols=["Constant", "Value", "Role", "Status"],
      col_w=[3.3, 2.0, 5.2, 1.7],
      rows=[
          ["support_rate", "0.60", "× qualifying cost — the co-funding rate", "CONFIRMED"],
          ["salary_floor", "5,000", "exclusion GATE G4 — person is EXCLUDED", "CONFIRMED"],
          ["salary_cap", "20,000", "arithmetic CLAMP min(salary, cap), person retained", "CONFIRMED"],
          ["hours_per_day", "8.8", "monthly capacity = weekdays × 8.8", "CONFIRMED"],
          ["weekdays_only", "True", "Mon–Fri; NETWORKDAYS replica", "CONFIRMED"],
          ["public_holiday_adjustment", "False", "holidays do NOT reduce working days", "ASSUMED (Q5)"],
          ["max_grant_amount", "42,000,000", "manpower/salary only ceiling", "CONFIRMED"],
          ["disbursement_threshold_pct", "0.70", "70% released, 30% held to completion", "CONFIRMED"],
          ["upskill_max_months", "9", "existing staff to PL3; new hires uncapped", "CONFIRMED"],
          ["upskill_cap_anchor", "first_qualifying", "which 9 months — vs training_start", "ASSUMED"],
          ["confidence_cutoff", "0.85", "SURFACING threshold — never a discard threshold", "ASSUMED"],
          ["variance_material_pct", "1.0", "|Δ%| > 1 reported as materially divergent", "ASSUMED (Q1)"],
          ["final_submission_days", "183", "final Audited Claim after QP end", "CONFIRMED"],
      ],
      highlight_col=3,
      note="Effective ceiling per person: 60% × 20,000 = $12,000/month. "
           "claim_is_audited is False in the POC, so the Details sheet always writes "
           "'UnauditedClaim' — the rate being confirmed is tracked separately from the "
           "claim being audited."),

    # ---------------------------------------------------------------- 4
    S("diagram", key="component_map",
      kicker="Architecture",
      title="Module map and the sealed core"),

    # ---------------------------------------------------------------- 5
    S("diagram", key="data_flow",
      kicker="Architecture",
      title="Data flow — one upload to a submission pack"),

    # ---------------------------------------------------------------- 6
    S("split",
      kicker="Ingest",
      title="Parsers that fail loudly and locate precisely",
      left_head="Layout is a contract, not a guess",
      left=[
          ("Pinned offsets.", "TS_HEADER_ROW=18, TS_DATA_START=19, SC_HEADER_ROW=14, "
           "SC_DATA_START=15, entity in G3. Missing sheet raises LayoutError."),
          ("Header synonyms + positional fallback.", "Emp No / Staff ID / Employee ID; "
           "Salary / Basic Pay / Base Salary. If headers are unrecognisable it falls back "
           "to column position rather than silently returning nothing."),
          ("Period inference.", "5 regexes over a Period / Pay Date / Pay Month column — a "
           "real date, '2024-01', or 'Jan 2024' — or from the filename "
           "(payslip-E001-2026-01.xlsx)."),
          ("Basic salary only.", "EXCLUDED_COMPONENTS drops CPF, bonus, AWS, allowances, "
           "COLA and airfare at the parser, so a non-qualifying component cannot leak "
           "downstream into a figure."),
      ],
      right_head="A bad file degrades, it does not abort",
      right=[
          ("explain_ingest_error().", "Classifies the exception — missing sheet, no Basic "
           "Salary column, unreadable period, duplicate row, not-a-zip — and returns an "
           "HR-readable why + fix into PipelineResult.errors."),
          ("Multi-file merge.", "Every payroll file is parsed then de-duplicated to one row "
           "per (employee_id, year, month), first wins. 27 individual payslip files produce "
           "the same total as one consolidated register."),
          ("Evidence at read time.", "Every parsed field carries its source_refs. This is "
           "the FR-7 hook and it is asserted by test_every_field_has_evidence_ref."),
      ],
      note="timesheet.py 648 · salary.py 451 · rse_list.py 223 lines"),

    # ---------------------------------------------------------------- 7
    S("code",
      kicker="Domain",
      title="Frozen models and an Excel-faithful calendar",
      intro="12 frozen dataclasses carry the contracts between layers. The calendar is a "
            "deliberate replica of Excel's NETWORKDAYS, because the EDB worked example and "
            "the internal workbook both depend on that exact convention.",
      code=[
          ("# models.py — the evidence pointer, threaded everywhere", "acc"),
          "@dataclass(frozen=True)",
          "class EvidenceRef:",
          "    file: str          # 'internal_ANS.xlsx'",
          "    sheet: str         # 'Time Sheet'",
          "    cell_or_row: str   # 'G19'",
          "    label: str         # 'monthly hours, Mar'",
          "",
          ("# calendar_utils.py — weekdays only, no PH adjustment", "acc"),
          "def worked_weekdays(start, end) -> int",
          "def weekdays_in_month(year, month) -> int",
          "def networkdays(start, end) -> int   # Excel replica",
          "def month_fraction(y, m, claim_start, claim_end) -> float",
      ],
      bullets=[
          ("Why replicate rather than import.", "The internal workbook computes capacity with "
           "NETWORKDAYS(join, left) × 8.8. Any divergence in the weekday convention shows up "
           "as a cent-level mismatch against the EDB oracle."),
          ("15 calendar tests", "pin it against Excel: partial months (13/23 Jan 2018), leap "
           "February, a weekend-only span returning 0."),
          ("Public holidays are the open question.", "public_holiday_adjustment=False is "
           "ASSUMED (PRD §10 Q5). If the auditor rules otherwise it is a one-line config "
           "change, not a refactor — which is exactly why it is config."),
      ]),

    # ---------------------------------------------------------------- 8
    S("table",
      kicker="Validation",
      title="Seven gates, each with a reason and a cell",
      intro="Gates run per person-month. Every gate returns a grounded reason AND an "
            "EvidenceRef — never generic error text, because 'not eligible' with no cell "
            "reference is useless to both HR and the auditor.",
      cols=["Gate", "Rule", "Authority", "On failure"],
      col_w=[1.0, 5.0, 3.6, 2.6],
      rows=[
          ["G1", "Local — SG citizen or PR", "RSE list + Time Sheet col E", "EXCLUDED"],
          ["G2", "ECMF-validated RSE", "RSE list + Time Sheet col H", "EXCLUDED"],
          ["G3", "Not enjoying another government cash grant", "Time Sheet col I", "EXCLUDED"],
          ["G4", "Basic monthly salary ≥ S$5,000", "Payslip", "EXCLUDED / BLOCKED*"],
          ["G5", "Designation not in a non-qualifying category", "Time Sheet col G", "EXCLUDED"],
          ["G6", "Involvement period overlaps the claim period", "Staff Costs C1/C2", "EXCLUDED / BLOCKED*"],
          ["G7", "Payslip evidence exists for the month", "Document check", "BLOCKED"],
      ],
      note="* G4 and G6 are CONDITIONAL blockers: they block only when source_ref is None, "
           "i.e. the rule could not be evaluated. A salary of 4,800 is a substantive "
           "EXCLUSION; a missing salary is a fixable BLOCK. Conflating the two would either "
           "hide an ineligible person or make a re-upload look like an appeal.",
      bullets=[
          ("G5 is deterministic keyword logic, not the LLM.", "A whole-word hit on one of the "
           "7 non-qualifying categories — Marketing, Finance, Sales, HR, Admin, Facilities "
           "Mgmt, Legal — hard-fails. A _TECH_TERMS hit passes. Anything else passes "
           "provisionally and is marked needs_review. The model only ever judges the "
           "needs_review set, and never overrides the gate."),
      ]),

    # ---------------------------------------------------------------- 9
    S("code",
      kicker="Validation",
      title="Verdict algebra — exclusion beats block",
      intro="Three statuses, strict precedence. The ordering matters: a person who is both "
            "ineligible and missing a document must read as EXCLUDED, or HR would chase a "
            "payslip for someone who can never be claimed.",
      code=[
          ("# validate/verdict.py", "acc"),
          "EXCLUDED  >  BLOCKED  >  QUALIFIES",
          "",
          "_ALWAYS_BLOCKER_GATES      = {G7}    # missing payslip",
          "_CONDITIONAL_BLOCKER_GATES = {G4, G6}",
          "    # ^ blocks ONLY when source_ref is None",
          "",
          ("# two-layer salary rule — different kinds of thing", "acc"),
          "salary <  5,000  ->  GATE G4 fails  ->  EXCLUDED",
          "salary >= 5,000  ->  min(salary, 20_000)  ->  RETAINED, clamped",
      ],
      bullets=[
          ("The floor is a gate; the cap is a clamp.", "Treating the 20,000 cap as an "
           "exclusion would drop the most senior researchers from the claim entirely. "
           "ANS-004 at $23,000/month qualifies and claims on 20,000."),
          ("Cross-checks never change a verdict.", "4 kinds — ECMF flag conflict, hours over "
           "capacity, payslip basic vs Staff Costs [A], payslip coverage vs dates. Each "
           "warning carries BOTH conflicting values so HR can adjudicate."),
          ("Nothing is ever silently dropped.", "test_outputs.py asserts every person with "
           "not qualifies appears in the Issues-to-fix sheet. Amber = fixable BLOCKED, "
           "red = EXCLUDED, confirm the reason."),
      ]),

    # ---------------------------------------------------------------- 10
    S("split",
      kicker="Validation",
      title="Document completeness as a matrix",
      left_head="19 DocTypes, scoped and graded",
      left=[
          ("Three scopes.", "PERSON_MONTH (a payslip for a claimed month), PERSON (CPF/bank "
           "statement), ENTITY (the ECMF RSE list, the internal workbook, the EDB template)."),
          ("Four blockers, fifteen warnings.", "BLOCKER: payslip, ECMF RSE list, internal "
           "workbook, EDB template. Everything else degrades the claim without stopping it."),
          ("Cells, not booleans.", "Each employee × month × doc cell is present / missing / "
           "inconsistent, rolled up to EmployeeRollup then EntityRollup."),
          ("Severities are ASSUMED.", "Pending the auditor's confirmed document list "
           "(PRD §10 Q4). The wider HR checklist — LoA, PL3 confirmation, daily clocking, "
           "AI artifacts — is presence-checked only, never parsed."),
      ],
      right_head="Re-upload is purity, not patching",
      right=[
          ("build_completeness recomputes from scratch.", "There is no incremental mutation "
           "path, so 'only the affected cells flip' is a property of the design rather than "
           "a behaviour that has to be tested into existence."),
          ("The UI gate is real.", "Results.tsx:1031 — gated = step === 0 && "
           "blockers.length > 0 && !acknowledged. Continue is disabled until HR either "
           "re-uploads the document or explicitly acknowledges the gap, in which case the "
           "affected people are excluded from the claim."),
          ("DoD-2.", "Fix the missing-payslip case by re-upload and the blocker clears "
           "without redoing anything else."),
      ],
      note="completeness.py is 856 lines — the largest module in the codebase, and the one "
           "with no dedicated test file. Coverage is indirect, via the three test_real_* "
           "end-to-end gate tests."),

    # ---------------------------------------------------------------- 11
    S("code",
      kicker="Calculation — Method A",
      title="EDB monthly pro-ration: the submitted figure",
      intro="Method A is EDB's official method and the only number that goes on the "
            "submission. Full precision throughout; exactly one rounding step.",
      code=[
          ("# calc/method_a.py", "acc"),
          "qualifying_cost = Σ over months m of:",
          "      capped_salary(m) × month_fraction(m) × time_contribution(m)",
          "",
          "capped_salary(m)     = min(basic_salary(m), 20_000)",
          "month_fraction(m)    = worked_weekdays / weekdays(m)",
          "                       # 1.0 for a whole month",
          "time_contribution(m) = min(1.0, hours(m) / (weekdays(m) × 8.8))",
          "",
          "claim = round(qualifying_cost_total × 0.60, 2)  # ONLY round()",
      ],
      bullets=[
          ("The cent rule.", "Per-month costs and the running total are never pre-rounded. "
           "The single round() mirrors the template's own I = ROUND(G×H, 2). Pre-rounding "
           "monthly figures drifts against the hand-calc control by cents — which is "
           "precisely what an auditor sampling to the cent would find."),
          ("time_contribution is clamped, [D3] is not.", "Method A caps time at 100%; the "
           "internal sheet's ratio can exceed it. That asymmetry is one source of the "
           "A-vs-B variance."),
          ("9-month upskill cap.", "_apply_upskill_cap keeps the earliest qualifying months "
           "for UPSKILLED/RESKILLED only. New hires and unknown hire types are never "
           "capped; the result carries months_capped so the truncation is visible."),
      ]),

    # ---------------------------------------------------------------- 12
    S("stats",
      kicker="Calculation — Method A",
      title="Pinned to EDB's own worked example",
      intro="The template ships a sheet, 'Salary Pro-ration E.g.', containing EDB's "
            "authoritative worked example. It is the non-negotiable oracle: if this figure "
            "moves, the engine is wrong.",
      stats=[
          ("$7,310.87", "EDB worked example", "9,500 · 15 Jan–31 Mar 2018 · @ 30%, THEIR rate"),
          ("13 / 23", "January month_fraction", "asserted exactly, not approximately"),
          ("$24,369.56…", "qualifying cost", "carried unrounded — no pre-rounding drift"),
          ("11", "Method A tests", "oracle, cap clamp, joiner fraction, upskill cap"),
      ],
      code=[
          ("# tests/test_method_a.py:74 — the rate is pinned deliberately", "acc"),
          "# EDB's published example is at their stated 30% support; pin it explicitly",
          "# so this method check stays independent of our scheme's confirmed 60% rate.",
          "settings_30 = replace(settings, support_rate=0.30)",
          "assert compute_method_a(...).claim_amount == 7310.87",
      ],
      note="Verified live: docs/demo/verify_calcs.py re-derives every Method A figure "
           "independently and reports ALL CHECKS PASSED, including ANS-004 capped every "
           "month, ANS-005 → $0.00, and ANS-002's 14/22 joiner fraction."),

    # ---------------------------------------------------------------- 13
    S("code",
      kicker="Calculation — Method B",
      title="The internal sheet, replicated quirks and all",
      intro="Method B reproduces HR's Staff Costs sheet so its figures can be reconciled. "
            "Its four quirks are PRESERVED AS FLAGS, never corrected — 'fixing' them would "
            "silently disagree with the workbook HR is looking at.",
      code=[
          ("# calc/method_b.py", "acc"),
          "[B]  = 'N/A' if salary < 5_000 else min(salary, 20_000)",
          "[D1] = NETWORKDAYS(date_join, date_left) × 8.8      # full employment span",
          "[D2] = total project hours;  New Hire -> 'N/A'",
          "[D3] = 1.0 if New Hire else [D2] / [D1]            # NOT clamped",
          "[E]  = [B] × [D3]                                   # 'N/A' propagates",
          "",
          "claim_amount = round([E] × support_rate, 2)",
      ],
      table_cols=["Flag on MethodBDetail", "The quirk being preserved"],
      table_col_w=[4.4, 7.4],
      table_rows=[
          ["new_hire_forced_100", "New Hire gets [D3]=100% with no timesheet evidence at all"],
          ["b_annual_labelled_but_monthly", "the header says 'annual'; the formula yields a monthly figure"],
          ["b_below_floor_na", "below the floor, [E] is the STRING 'N/A' — not zero"],
          ["d3_over_100", "the hours ratio is unclamped and can exceed 100%"],
      ],
      note="[D1] uses NETWORKDAYS(join, left) × 8.8, not the header's C2 − C1. "
           "reconcile() compares the recomputed [E] against the workbook's surfaced [E] at "
           "1e-6, handling both-N/A, blank and mixed cases distinctly."),

    # ---------------------------------------------------------------- 14
    S("image",
      kicker="Calculation — variance",
      title="Where the two methods genuinely disagree",
      img="live_5b_variance.png",
      crop=(0.0, 0.52, 1.0, 1.0),
      bullets=[
          ("This is not a rounding difference.", "Method A pro-rates a capped monthly salary "
           "across months. Method B applies a single hours ratio over the whole employment "
           "span. On the sample roster every row differs materially."),
          ("The audit-risk row.", "Chua Mei Ling (ANS-005) — a New Hire with no timesheet "
           "hours. Method B forces [D3]=100% and produces $3,900.00 with no supporting "
           "evidence; Method A produces $0.00. Flagged 'Verify (New Hire)' regardless of "
           "magnitude, because the size of the gap is not the point — the missing evidence is."),
          ("Both ship, on purpose.", "PRD §10 Q1 — which method governs each edge case is "
           "unresolved pending an EDB/auditor ruling. The POC computes both and reports the "
           "variance rather than pre-empting the decision."),
      ],
      note=f"Live capture, sample_data @ 60%. Total claim {VERIFIED['total_claim']} — ties "
           f"exactly to eval_report.json. Header stat reads 13 claimable +1 eligible at $0: "
           f"{VERIFIED['qualifying']} QUALIFIES verdicts, of which "
           f"{VERIFIED['nonzero']} carry a non-zero claim."),

    # ---------------------------------------------------------------- 15
    S("diagram", key="trust_boundary",
      kicker="LLM layer",
      title="The trust boundary is a test, not a docstring"),

    # ---------------------------------------------------------------- 16
    S("code",
      kicker="LLM layer",
      title="Provider-agnostic, schema-constrained, replayable",
      intro="One client wraps any OpenAI-compatible endpoint — the local Qwen 3.6 35B A3B on "
            "vLLM by default. The pipeline runs identically with no model at all.",
      code=[
          ("# llm/client.py", "acc"),
          "def call(self, prompt, *, schema=None, source_ref=None,",
          "         confidence_hint=None) -> LLMResult",
          "",
          "cache_key = sha256(canonical_json(prompt, model, schema))",
          "  # source_ref persisted but EXCLUDED from the key",
          "",
          "transport: injected (tests) > openai (enabled) > None",
          "no transport -> typed 'unavailable'. call() NEVER raises.",
          "",
          "temperature = 0.0",
          "response_format = json_schema, strict: True",
      ],
      bullets=[
          ("The honest determinism claim.", "Temperature 0 maximises stability but GPU "
           "inference is not bit-exact. The cache-and-replay log is the actual determinism "
           "guarantee — and because source_ref is outside the cache key, the same question "
           "about the same figure replays identically regardless of which document surfaced it."),
          ("Graceful degradation is a feature, not a fallback.", "The deterministic pipeline "
           "is the product; the model is an assistant on top of it. "
           "test_no_endpoint_still_replays_cache pins that."),
          ("Four schemas, no prompt files.", "_EXTRACT_SCHEMA, _JUDGE_SCHEMA, _MATCH_SCHEMA, "
           "_ANSWER_SCHEMA. Prompts are inline functions, versioned with the code that "
           "depends on them."),
      ]),

    # ---------------------------------------------------------------- 17
    S("split",
      kicker="LLM layer",
      title="FR-9 / FR-10 / FR-11 — deterministic first, model second",
      left_head="Each capability narrows what the model may touch",
      left=[
          ("FR-9 extraction.", "Payslip → fixed JSON with a 0–1 confidence and a source "
           "location per field. The deterministic parser stays authoritative; the model's "
           "output produces cross-check ADVISORIES, never a replacement figure."),
          ("FR-10 designation judging.", "judge_review_cases batches only the employees the "
           "G5 keyword gate already marked needs_review. The judgement reports agreement or "
           "disagreement with the gate and never overrides it."),
          ("FR-11 reconciliation.", "Deterministic first: _norm_name, a token-frozenset "
           "_name_key for word-order variants, Levenshtein ≤ 1 for typos. Exact employee-ID "
           "auto-accepts with used_model False. Only genuinely ambiguous pairs reach the "
           "model, and they land in an HR confirmation queue."),
      ],
      right_head="Nothing is discarded, everything is surfaced",
      right=[
          ("confidence_cutoff = 0.85 is a SURFACING threshold.", "Below it, the response is "
           "still shown — annotated with a plain-language reason: 'The model reported 72% "
           "confidence, below the 85% review threshold.' HR is never handed a black box, and "
           "never handed a silent omission either."),
          ("A failed check annotates, it does not suppress.", "groundedness.py:12 states it "
           "directly. An ungrounded answer is displayed with ⚠ Unverified figure attached."),
          ("Why this ordering.", "Every LLM capability sits where a wrong answer costs an "
           "advisory, a review flag or a queue entry — never a claim figure."),
      ]),

    # ---------------------------------------------------------------- 18
    S("code",
      kicker="LLM layer",
      title="Audit Q&A — a deterministic router with a verified tail",
      intro="One public method. The router is ordinary Python; the model speaks on exactly "
            "one branch, and every branch is verified before display.",
      code=[
          ("# llm/qa.py", "acc"),
          "def answer(self, question, result=None) -> Answer:",
          "    return self._verify(self._route(q, result), result, q)",
          "",
          ("# _route — first match wins, model reached only at the end", "acc"),
          "1  _find_employee(live)   -> _employee / _evidence / _docs",
          "2  _find_record_in_db()   -> _record_from_db  # exact SQL",
          "3  total intent           -> _totals",
          "4  counting / listing     -> _roster",
          "5  fallback               -> _scheme  <- ONLY model branch",
      ],
      bullets=[
          ("Figures come from rows, prose comes from retrieval.", "Branches 1–4 read "
           "structured values — the figures ARE the rows, so confidence is 1.0 by "
           "construction. Only branch 5 generates language."),
          ("_verify runs on every branch, including the deterministic ones.", "allowed_figures "
           "unions the live PipelineResult, persisted store rows via exact SQL, numerals "
           "appearing verbatim in retrieved scheme text, and 12 config constants. Anything "
           "outside that set within 0.01 is flagged."),
          ("Exactly one derivation is permitted.", "Cap-then-rate, and only on figures the "
           "user named in the question. Widening the bases to the whole roster would make "
           "almost any five-figure number derivable from some row × 0.6 — which is the "
           "hallucination the check exists to catch."),
      ]),

    # ---------------------------------------------------------------- 19
    S("image",
      kicker="LLM layer",
      title="Groundedness is shown, not claimed",
      img="live_8_chat.png",
      crop=(0.707, 0.352, 0.995, 0.947),
      bullets=[
          ("A verified answer, live.", "Offline mode, no model connected — the badge reads "
           "\u201c\u2713 Figures verified \u00b7 confidence 100%\u201d because the figure "
           "IS a claim row: the router matched ANS-001 in the live result and read "
           "$34,200.00 straight out of it."),
          ("The badge is measured, not decorative.", "check() re-extracts every figure from "
           "the rendered answer and matches it against allowed_figures() within "
           "Decimal('0.01') before display. An answer that failed would still be shown, "
           "annotated \u201c\u26a0 Unverified figure\u201d with a plain-language reason."),
          ("It volunteers the caveat.", "The answer names the Method B disagreement unprompted "
           "and points at the next action \u2014 \u201cfetch the evidence for Lim Jia Hao\u201d "
           "\u2014 rather than presenting one number as settled."),
          ("Note the header parity.", "13 claimable, 1 needs a document, 5 not eligible, "
           "$492,934.55 \u2014 the same figures the eval harness reports, because both read "
           "the same PipelineResult."),
      ],
      note="Captured from the running app on sample_data at a 60% support rate. Cosmetic bug "
           "visible here and left alone: the chat panel renders the model's markdown "
           "literally, so **bold** shows its asterisks."),

    # ---------------------------------------------------------------- 20
    S("table",
      kicker="Persistence",
      title="One local SQLite file, employee_id as partition key",
      intro="16 tables declared in db/schema.py. All writes are UPSERTs; no table has a "
            "DEFAULT CURRENT_TIMESTAMP, so time is always passed in — a precondition for "
            "reproducible runs. Migrations are PRAGMA table_info + ALTER TABLE, idempotent.",
      cols=["Table", "Purpose", "Live rows"],
      col_w=[3.2, 6.6, 2.4],
      rows=[
          ["employee", "roster identity, designation, hire type, citizenship", "34"],
          ["employee_identifier", "(id_type, id_value) → employee_id; NRIC, alias, email", "21"],
          ["employee_document", "the FR-2 completeness matrix, persisted", "387"],
          ["person_month", "(employee, year, month) basic_salary + hours", "0"],
          ["gate_result", "one row per (employee, gate) with reason + ref_id", "238"],
          ["verdict", "status + failed_gates JSON + reasons JSON", "34"],
          ["calc_result", "(employee, method) — 34 people × Method A and B", "68"],
          ["evidence_ref", "UNIQUE(employee_id, figure_key) — the FR-7 spine", "312"],
          ["document / doc_blob / doc_link", "metadata split from bytes so scans skip content", "3 blobs"],
          ["llm_log", "prompt, raw response, parsed, confidence, run_id", "0"],
          ["run_manifest", "config_hash, support_rate, code_version", "0"],
          ["chunk / chunk_vec", "vec0 virtual table, FLOAT[384] — sqlite-vec active", "0"],
      ],
      highlight_col=2,
      note="Row counts are the COMMITTED DEV DB, accumulated across sample_data + testkit + "
           "altdata runs — not one claim. Two-path retrieval is the design: exact SQL for "
           "figures, vector search for narrative. chunk_vec is created and sqlite-vec is "
           "loaded (its shadow tables are present), but populating it is the remaining step, "
           "so today's narrative path is keyword retrieval over the 11-entry SCHEME_KB. "
           "person_month, llm_log and run_manifest all have writers that neither "
           "front-end calls yet — the per-month breakdown is recomputed from the "
           "workbooks each run, and the LLM trail lives in a 101 KB JSON replay cache."),

    # ---------------------------------------------------------------- 20
    S("diagram", key="evidence_trail",
      kicker="Evidence",
      title="Every figure back to its cell"),

    # ---------------------------------------------------------------- 21
    S("split",
      kicker="Outputs",
      title="Three writers for three readers",
      left_head="Template fidelity is asserted, not hoped for",
      left=[
          ("edb_writer.py — EDB's official template.", "shutil.copyfile then load_workbook "
           "with formulas intact. Writes only the value cells (a)–(h) from row 5, plus the "
           "Details header. Re-creates I=ROUND(G{row}*H{row},2) and the K/L breach formulas "
           "for NEW ROWS ONLY, leaving the template's shipped rows untouched."),
          ("_assert_fidelity re-opens the saved file", "and verifies H2/I2 still start with "
           "=SUM, that column K is still hidden, and that the last row's column I is still a "
           "ROUND formula. The check runs against the artifact, not the in-memory workbook."),
          ("A documented template bug, deliberately not fixed.", "The I3 header label reads "
           "'= i × j' while the live formula is ROUND(G×H,2). Matching the label would "
           "change the arithmetic EDB's own template performs."),
      ],
      right_head="Only qualifying rows, everyone else reported",
      right=[
          ("soe.py — Statement of Expenditure.", "6 styled sheets: cover, SOE, "
           "month-by-month workings, the A-vs-B cross-check, the evidence trail with "
           "file/sheet/cell, and excluded staff with reasons. This is the auditor's document."),
          ("reports.py — Issues to fix.", "HR's action list. Amber 'Fixable — upload the "
           "missing document and re-run'; red 'Not claimable — confirm the reason'."),
          ("One submission file per entity that has at least one qualifier.", "Uses the "
           "HR-uploaded template when present, else the shipped docs/EDB_Output Template.xlsx."),
      ]),

    # ---------------------------------------------------------------- 22
    S("table",
      kicker="Surfaces",
      title="Six endpoints, NDJSON streaming, one seam",
      intro="Both front-ends converge on run_pipeline(). The UI computes nothing — every "
            "figure on screen came from the deterministic pipeline.",
      cols=["Method", "Path", "Purpose"],
      col_w=[1.3, 3.6, 7.3],
      rows=[
          ["GET", "/api/health", "llm_enabled, support_rate, claim_period, application_no — drives the top bar"],
          ["POST", "/api/analyze", "multipart upload + 11 checklist flags → StreamingResponse of NDJSON"],
          ["POST", "/api/preview", "{session, file, sheet, cell} → the cited sheet as a grid + focus cell"],
          ["POST", "/api/chat", "{session, question} → text, citations, grounded, confidence, mode"],
          ["GET", "/api/downloads/{session}", "builds the submission pack on first call"],
          ["GET", "/api/download/{session}/{file}", "FileResponse of one xlsx"],
      ],
      bullets=[
          ("Streaming is narrative, on purpose.", "progress events are emitted with 0.35s "
           "pauses so the loading screen reads as an audit trail being assembled rather than "
           "a spinner. Then one result or one error event."),
          ("Session state is in-memory only.", "a module-level dict keyed by uuid4 — no "
           "multi-worker support, lost on restart. Acceptable for a single-user local POC; "
           "the first thing to change for pilot."),
          ("Persistence is best-effort.", "persist_result is wrapped so a store failure can "
           "never lose a computed claim."),
      ]),

    # ---------------------------------------------------------------- 23
    S("stats",
      kicker="Determinism",
      title="Same inputs, byte-identical outputs — demonstrated",
      intro="Determinism is an audit requirement, so it is tested as a property rather than "
            "asserted as an intention. Re-verified live while building this deck.",
      stats=[
          ("OK", "shasum -c on a re-run", "eval_report.json byte-identical; no timestamp in the harness"),
          ("9", "same-input identity assertions", "method_a, method_b, variance, verdict, ingest, cache"),
          ("3", "import-boundary tests", "subprocess + sys.modules: calc/ and validate/ never see llm/"),
          ("131", "tests passing", f"across {VERIFIED['test_files']} files, in 11.3s"),
      ],
      code=[
          ("# the boundary test that makes the architecture diagram true", "acc"),
          "shasum eval_report.json > before",
          "python -m edb_claim.eval",
          "shasum -c before          ->  eval_report.json: OK",
          "",
          "# tests/test_method_a.py — AST over real import statements, not the docstring",
          "test_calc_does_not_import_llm      test_variance_does_not_import_llm",
          "test_verdict_does_not_import_llm",
      ],
      note="The AST approach is deliberate: a naive grep would match the module name in a "
           "docstring that merely explains the boundary. These tests inspect real import "
           "statements, then confirm in a subprocess that no edb_claim.llm* module was loaded."),

    # ---------------------------------------------------------------- 24
    S("eval",
      kicker="Evaluation",
      title="What 33/33 does and does not mean",
      headline="33 / 33 probes emitted zero unsupported figures",
      subhead='mode: "offline"  ·  model: null  ·  used_model: false on all 33',
      claim="Groundedness is an anti-hallucination gate, not a correctness gate.",
      body=[
          ("What the scorer actually checks.", "Four conditions per probe: the grounded flag "
           "matches expectation, the router landed on the declared branch, the answer quotes "
           "the pipeline figure to the cent (Decimal('0.01')), and expected substrings are "
           "present. Plus FR-14: an ungrounded or low-confidence answer must carry a "
           "confidence_reason or it fails."),
          ("Why a perfect offline score is structural.", "Offline, _scheme returns the "
           "top keyword-retrieved SCHEME_KB entry VERBATIM — _retrieve scores "
           "len(qtok & cand) + 2×len(title ∩ qtok) over 11 inline entries. A non-answer "
           "satisfies a groundedness gate vacuously, because it contains no figure to be wrong."),
          ("So all 5 adversarial probes pass by deflection, not by declining.",
           "derivation · unknown_person · prompt_injection · off_topic · hypothetical. "
           "'What is the capital of France?' returns the RIS(C) scheme overview. "
           "'Ignore your previous instructions' returns floor/cap boilerplate. Neither is a "
           "refusal — and a refusal is what the criterion should be."),
          ("Three of four FR-14 scorers are unimplemented.", "extraction, designation and "
           "reconciliation are registered as explicit status:'not_implemented' stubs so they "
           "appear in every report rather than being silently absent."),
      ],
      quote='"a 100% score over 0 model answers proves nothing about the model."',
      quote_src="edb_claim/eval/harness.py:238 — the harness says so about itself",
      corollary="The model-connected run is the one that can fail. It has not been run: the "
                "Qwen endpoint is deferred, so every number above describes the deterministic "
                "paths only.",
      taxonomy=[("8", "figure (data)"), ("9", "exclusion / roster"), ("3", "evidence"),
                ("8", "scheme"), ("5", "adversarial")],
      note="Ground truth is DERIVED, never hardcoded: expected figures come from a live "
           "pipeline run over sample_data/ at eval time, so the question set cannot drift "
           "from the fixtures. The one pinned constant in the project is the Method A "
           "oracle, 7,310.87, kept in tests/test_method_a.py."),

    # ---------------------------------------------------------------- 25
    S("table",
      kicker="Ground truth",
      title="The 13 deliberate error cases",
      intro="PRD §8 defines the synthetic failure set the whole evaluation rests on. All 13 "
            "exist as fixtures in sample_data/expectations.json; the last column is where "
            "coverage is thinner than the fixture set suggests.",
      cols=["#", "Case", "Fixture", "Expected", "Unit test"],
      col_w=[0.6, 4.5, 1.7, 2.6, 2.1],
      rows=[
          ["1", "Standard full-period RSE", "ANS-001", "A = $34,200.00", "yes"],
          ["2", "Mid-period joiner / leaver", "ANS-002/003", "Mar = 14/22", "yes"],
          ["3", "Salary S$4,800 below the floor", "DSG-001", "EXCLUDED · G4", "yes"],
          ["4", "Salary S$23,000 hits the cap", "ANS-004", "A = $72,000.00", "yes"],
          ["5", "Foreigner", "DSG-002", "EXCLUDED · G1", "yes"],
          ["6", "Not ECMF-validated", "DSG-003", "EXCLUDED · G2", "none"],
          ["7", "Enjoying another government grant", "DSG-004", "EXCLUDED · G3", "none"],
          ["8", "'HR Manager' designation", "DSG-005", "EXCLUDED · G5", "none"],
          ["9", "New Hire, no timesheet hours", "ANS-005", "A = $0.00, B > 0", "yes"],
          ["10", "Missing payslip for a month", "DSG-006", "BLOCKED · G7", "yes"],
          ["11", "Hours exceed monthly capacity", "ANS-006", "capacity warning", "none"],
          ["12", "Name variant across documents", "ANS-003", "HR match queue", "yes"],
          ["13", "Ambiguous designation", "ANS-007", "needs_review", "yes"],
      ],
      highlight_col=4,
      note="9 of 13 have a dedicated unit test. The 4 that do not — G2, G3, G5 and the "
           "hours-over-capacity cross-check — are covered only indirectly, through the three "
           "test_real_* end-to-end gate tests and the eval probes. PRD §11 DoD-1 asserts all "
           "13 are caught, but that assertion lives in print-based scripts "
           "(sample_data/_verify.py, docs/demo/verify_calcs.py), not in a pytest acceptance "
           "module — PLAN.md T21 has no test file."),

    # ---------------------------------------------------------------- 26
    S("closing",
      kicker="Status",
      title="What is solid, what is open",
      solid_head="Verified end to end",
      solid=[
          "131 tests passing across 15 files",
          "Method A pinned to EDB's own $7,310.87 oracle, to the cent",
          "eval_report.json byte-identical on re-run",
          "3 AST tests hold the calc/ never-imports-llm/ boundary",
          "Template fidelity asserted against the saved artifact",
          "Every figure traceable to file · sheet · cell (312 refs)",
      ],
      open_head="Open, and deliberately not decided in code",
      open=[
          ("Q1 — method ruling", "which of A or B governs each edge case. Both ship, variance flagged."),
          ("Q3 — New-Hire 100% time", "acceptable without timesheets? Flagged, not resolved."),
          ("Q4 — auditor's document list", "FR-2 severities stay ASSUMED until confirmed."),
          ("Q5 — public holidays", "assumed not to reduce working days."),
          ("Q8 — entity count", "PRD says 17; the workbook's IHQ→GEC/GTO/IT split gives 18, and the code ships 18."),
          ("Q2 — CLOSED", "support rate confirmed at 60% (was 30% assumed)."),
      ],
      gaps_head="Known gaps",
      gaps=[
          "completeness.py (856 lines) and gates.py (455) have no dedicated test file",
          "3 of 4 FR-14 scorers are not_implemented stubs; no model-connected eval run yet",
          "chunk/chunk_vec unpopulated — no chunker or embedder; narrative retrieval is keyword",
          "llm_log and run_manifest have writers no front-end calls",
          "API session state is in-memory only, single worker",
      ],
      close="Questions & discussion"),
]
