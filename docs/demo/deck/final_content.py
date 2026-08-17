"""Slide content for the presenter deck (docs/demo/EDB_Final_Deck.pptx).

The spine here is a FILL map keyed by the 1-based slide number in
``docs/demo/edb automation final template.pptx``, whose odd slides are section
dividers (left untouched) and whose even slides are the content slides this
module fills. Slides 12, 14, 16 and 22 are absent on purpose: the first three
were already pasted in from the technical deep-dive, and 22 is where the demo
video goes by hand.

Specs are the same dicts ``render_pptx`` already consumes, so nothing here
knows about shapes or coordinates.

Every figure is taken from the running system (see deck/content.py:VERIFIED and
edb_claim/config.py), not from the PRD — the PRD is stale on the support rate
(30% -> 0.60 CONFIRMED) and the entity count (17 -> 18).
"""

from content import VERIFIED

TESTS = VERIFIED["tests"]                 # 131
TEST_FILES = VERIFIED["test_files"]       # 15
TOTAL = VERIFIED["total_claim"]           # $492,934.55 @ 60% on sample_data/
EVIDENCE = VERIFIED["evidence_rows"]      # 312
ENTITIES = 18                             # config.py: 16 base UENs, IHQ -> GEC/GTO/IT


def S(kind, **kw):
    d = {"kind": kind}
    d.update(kw)
    return d


# --------------------------------------------------------------------------
# slides filled in place  ·  key = 1-based slide number in the template
# --------------------------------------------------------------------------
FILL = {

    # ---- 2 · Problem Statement ------------------------------------------
    2: S("bullets",
         kicker="The problem",
         title="A grant claim is an evidence problem, not an arithmetic one",
         strip_all=True,      # the template's own two points are re-stated below
         items=[
             ("EDB funds the research headcount.", "The Economic Development Board "
              "co-funds the salaries of qualifying research staff hired for approved "
              "research projects — a material amount to the organisation, claimed "
              f"across {ENTITIES} participating entities and a three-year qualifying "
              "period."),
             ("Preparing it is manual, and repeats every claim.", "HR re-keys the same "
              "people out of three separate workbook contracts — an internal "
              "checklist/timesheet per entity, a payroll register, an ECMF-validated "
              "researcher list — into EDB's official template, by hand, per person, "
              "per month."),
             ("The audit is the real constraint.", "An ACRA-registered Public Accountant "
              "performs SSRS 4400 agreed-upon procedures and samples at least 85% of the "
              "claimed value against the Statement of Expenditure. Almost every claim row "
              "must be able to show where its number came from."),
             ("So evidence cannot be reconstructed afterwards.", "It has to be captured at "
              "the moment a value is read out of a workbook and carried all the way to the "
              "submission — file, sheet, cell."),
             ("And the answer must not move.", "Determinism is an audit property: a re-run "
              "during the audit window has to produce the same figures, or the claim is "
              "not defensible."),
         ],
         note="Out of scope by design: equipment and other cost categories, claims for "
              "foreign staff (flagged, never claimed), live HR/payroll integration, and "
              "anything that replaces the auditor's own procedures."),

    # ---- 4 · Solution ---------------------------------------------------
    4: S("bullets",
         kicker="The solution",
         title="An agentic system HR can trust with a financial number",
         strip_all=True,
         items=[
             ("An agentic document-verification system for HR.", "Upload the HR records "
              "and the system reads them, tracks what is missing, applies EDB's rules "
              "person by person and month by month, and produces the filled submission "
              "pack."),
             ("Harness engineering, because the subject is money.", "The intelligence is "
              "wrapped in guardrails: schema-constrained calls at temperature 0, a "
              "cache-and-replay log, and a hard boundary the model cannot cross."),
             ("The model proposes; the engine disposes.", "Every claim figure is computed "
              "in plain, auditable Python. The LLM only proposes extractions and "
              "judgements for HR to confirm — three tests assert that the calculation "
              "modules cannot even import the LLM layer."),
             ("Grounded retrieval for the assistant.", "Figure questions are answered by "
              "exact SQL over the rows the pipeline actually computed; scheme questions "
              "are answered from a curated knowledge base; \"fetch the evidence for "
              "<name>\" returns the source documents and cells, so HR can satisfy a "
              "re-verification request on the spot."),
             ("Evidence threaded from the parser.", f"{EVIDENCE} evidence references are "
              "live in the store — any figure on screen is one click from the cell it came "
              "from, and the same trail is exported for the Practitioner."),
             ("Both methods, and the disagreement between them.", "EDB's monthly "
              "pro-ration is what gets submitted; the internal hours-ratio method runs "
              "beside it as a second opinion, with a variance report — because the ruling "
              "on which governs every edge case is still pending."),
         ],
         note="Fully local: salary data is processed on the machine it was uploaded to. "
              "There is no external API call on claim data at any point."),

    # ---- 6 · Mental Model -----------------------------------------------
    6: S("code",
         kicker="Mental model",
         title="One identity, three rules that never bend",
         intro="Hold this and the rest of the system follows: the claim is a sum over "
               "person-months, and everything else exists to prove each term of it.",
         code=[
             ("# the whole claim, in one line", "acc"),
             "",
             "claim  =  support_rate  ×  Σ  over claimable months",
             "                             min(basic_salary, 20_000)",
             "                           × month_fraction        # weekdays worked / weekdays in month",
             "                           × time_on_project       # % from the timesheet",
             "",
             ("# and the constants that decide who is in the sum", "acc"),
             "",
             "support_rate = 0.60        CONFIRMED — EDB Support Package",
             "salary_floor = 5_000       below it the person is EXCLUDED, not clamped",
             "salary_cap   = 20_000      above it the salary is clamped, person retained",
             "hours_per_day = 8.8        weekdays only — no public-holiday adjustment",
             "",
             ("# effective ceiling per person:  0.60 × 20,000 = $12,000 / month", "acc"),
         ],
         bullets=[
             ("Arithmetic is Python.", "No model, no spreadsheet formula, no cell "
              "reference we cannot re-derive. Same inputs, same figures, every run."),
             ("The model proposes, the engine disposes.", "The LLM may suggest a reading "
              "or flag a borderline designation. It never writes a number."),
             ("Every figure has a cell.", "A value that cannot name its source workbook, "
              "sheet and cell does not belong in a claim."),
             ("Nothing is silently dropped.", "Excluded people leave with a reason and an "
              "authority. Low-confidence answers are shown with the reason they are "
              "low — never discarded."),
         ],
         note="The two floors are different animals and the distinction is worth "
              "$12,000: the S$5,000 floor is an eligibility gate that removes a person; "
              "the S$20,000 cap is arithmetic that keeps them."),

    # ---- 8 · Overall Workflow -------------------------------------------
    8: S("diagram", key="hr_journey",
         kicker="Overall workflow",
         title="How a claim flows — five guided stages"),

    # ---- 10 · Architecture (+2 inserted, see INSERTS) --------------------
    10: S("diagram", key="component_map",
          kicker="Architecture",
          title="Module map and the sealed core"),

    # ---- 14 · Evaluation -------------------------------------------------
    # Replaces the deep-dive evaluation slide that was pasted in here: same
    # figures, no jargon. Rows follow PRD §8 (the 13 planted cases), §11 (the
    # definition of done) and FR-14 (four checks, nothing discarded).
    14: S("table",
          clear=True,      # the pasted slide is a shape group, not a placeholder
          kicker="Evaluation",
          title="How we check the system is right",
          intro="Eight checks run on every build, against a synthetic staff list built to "
                "fail in known ways. Each one either passes or names what it found — and no "
                "score is reported without saying what that score covers.",
          cols=["What we check", "How we check it", "Where it stands"],
          col_w=[3.0, 5.9, 2.6],
          rows=[
              ["The money is right",
               "Compared to EDB's own published example, and to hand calculations",
               "Matches to the cent"],
              ["Every planted mistake is caught",
               "13 deliberate problems seeded in the staff list, one per person",
               "All 13 caught and labelled"],
              ["Nobody is set aside quietly",
               "Each exclusion carries its reason, the rule, and the cell behind it",
               "Checked on every run"],
              ["Same documents, same answer",
               "The claim is recalculated and the results compared figure by figure",
               "Identical every time"],
              ["The assistant invents nothing",
               "33 set questions; every number in an answer must match a calculated one",
               "33 of 33, none invented"],
              ["Nothing is hidden from HR",
               "Unsure answers are still shown, with a plain reason for the doubt",
               "Built in, always on"],
              ["Every figure traces to its source",
               "Follow any number to the file, the sheet and the cell it came from",
               "312 references, all resolve"],
              ["Payslips, job titles, names",
               "The three remaining checks in the plan, on the same staff list",
               "Set up, not yet scored"],
          ],
          bullets=[
              ("The 13 planted cases:", "salary under the minimum · salary above the "
               "ceiling · a foreigner · someone not on the approved researcher list · "
               "someone already on another grant · an HR job title · an unclear job title · "
               "a mid-month joiner · a mid-month leaver · a new hire with no hours logged · "
               "a missing payslip · hours above what the month allows · one person's name "
               "spelled two different ways"),
          ],
          note="What the 33 questions do and do not prove: they ran with no model attached, "
               "so they show the system will not put an unsupported number in front of HR — "
               "they do not grade how well a model writes. Grading that needs our own server's "
               "model connected. Nine of the 13 planted cases have their own automated test; "
               "the other four are covered by the end-to-end checks."),

    # ---- 18 · Deployment -------------------------------------------------
    18: S("diagram", key="deployment",
          strip_all=True,   # drops the "[on-prem nvidia dgx deployment]" stub
          kicker="Deployment",
          title="On-prem deployment — offline-capable by design"),

    # ---- 20 · Impact of the solution -------------------------------------
    20: S("split",
          strip_all=True,
          kicker="Impact",
          title="What changes for HR, and for the auditor",
          left_head="Manual today",
          left=[
              "Weeks of spreadsheet work per claim, repeated per entity and per month.",
              "The rate, the S$20,000 cap or an exclusion is easy to mis-apply — and hard "
              "to notice afterwards.",
              "Evidence is assembled at audit time, by hand, from whatever files can "
              "still be found.",
              "\"Where did this number come from?\" is a research task.",
              "A missing payslip is discovered late, by the auditor.",
              "Two calculation methods disagree quietly, in someone's working copy.",
          ],
          right_head="With this system",
          right=[
              "Upload to audit-ready submission pack in minutes, and repeatable on demand.",
              "The scheme rules are encoded once, in config, and applied to every person "
              "identically.",
              f"{EVIDENCE} evidence references are captured as the workbooks are parsed — "
              "the pack is assembled, not reconstructed.",
              "Any figure is one click from its file, sheet and cell — the same trail the "
              "Practitioner samples.",
              "The document check blocks the claim until the gap is fixed or explicitly "
              "acknowledged.",
              "Method A is submitted, Method B cross-checks it, and the variance is "
              "reported before the auditor sees it.",
          ],
          note=f"Verified on the running system: {TESTS} automated tests across "
               f"{TEST_FILES} files · Method A pinned to EDB's own published worked "
               f"example to the cent · {TOTAL} total claim across 14 qualifying staff on "
               f"the synthetic dataset at the 60% support rate · 33/33 assistant probes "
               f"emitted zero unsupported figures."),

    # ---- 24 · Scope of improvement ---------------------------------------
    24: S("bullets",
          strip_all=True,
          kicker="Scope of improvement",
          title="What we would build next, in order",
          items=[
              ("Semantic retrieval (T23).", "The store already carries a sqlite-vec "
               "vec0 table sized for 384-dimension embeddings; today the narrative path "
               "is lexical over a curated knowledge base. Computing embeddings turns it "
               "semantic without changing the figure path, which stays exact SQL."),
              ("The remaining three eval scorers (T24).", "Groundedness is implemented "
               "and scores 33/33; extraction, designation and reconciliation are "
               "registered as explicit stubs, so completing them is an addition rather "
               "than a refactor."),
              ("Run manifest and a determinism harness (T13).", "Persist config hash, "
               "support rate and code version per run so a re-run can be proven "
               "identical rather than assumed identical."),
              ("Widen what is persisted.", "Per-month salary rows and the LLM call log "
               "are schema-complete but not yet written on the API path."),
              ("Roll out across all entities.", f"The POC runs two synthetic entities; "
               f"the config carries all {ENTITIES}. Next is a real entity's FY2026 H1 "
               "data end to end."),
              ("Read from the source systems.", "Replace workbook upload with an HR/payroll "
               "feed, so the re-keying disappears rather than being validated."),
              ("Harden the deployment.", "A systemd unit or container image, a backup of "
               "the single database file, and a live-model evaluation run once the DGX "
               "endpoint is reachable again."),
          ],
          note="Two scheme questions are still open with EDB and the auditor, and are "
               "carried in config rather than decided in code: which method governs every "
               "edge case, and whether public holidays reduce working days."),

    # ---- 26 · Learnings ---------------------------------------------------
    26: S("bullets",
          strip_all=True,
          kicker="Learnings",
          title="What building this actually taught us",
          items=[
              ("A boundary has to be a test, not a docstring.", "\"The LLM never computes "
               "a figure\" is only true if something enforces it — so three tests import "
               "the calculation and validation packages in a subprocess and assert no LLM "
               "module ever reaches sys.modules."),
              ("Temperature 0 is not determinism.", "GPU inference is not bit-exact. The "
               "real guarantee is the cache-and-replay log keyed on a hash of prompt, "
               "model and schema — so the same question replays identically."),
              ("Replicate the source system's quirks; do not fix them.", "The internal "
               "sheet gives new hires 100% time and labels a monthly figure \"annual\". "
               "Reproducing both is what makes reconciliation meaningful — the variance "
               "report is where the disagreement belongs."),
              ("Anchor to someone else's answer.", "EDB publishes a worked example. "
               "Pinning Method A to it to the cent caught more real bugs than any "
               "hand-written expectation would have."),
              ("Low confidence is information, not noise.", "Surfacing a weak answer with "
               "a plain-language reason keeps a financial system out of black-box "
               "territory; discarding it hides the very case a human should see."),
              ("Design for the auditor, not the demo.", "\"Show me where this came from\" "
               "shaped the data model far more than any UI decision did — evidence is "
               "threaded from the parser because it cannot be recovered later."),
          ]),

    # ---- 28 · Conclusion --------------------------------------------------
    28: S("closing",
          strip_all=True,
          kicker="Conclusion",
          title="A POC that is finished, honest about its edges, and ready to pilot",
          solid_head="VERIFIED END TO END",
          solid=[
              f"{TESTS} tests across {TEST_FILES} files",
              "Method A pinned to EDB's published worked example, to the cent",
              f"{TOTAL} claimed across 14 qualifying staff on the synthetic set",
              f"{EVIDENCE} evidence references, each one click from its cell",
              "33/33 assistant probes with zero unsupported figures",
              "Runs on-prem, offline, with no external call on claim data",
          ],
          open_head="OPEN — DECISIONS, NOT MISSING CODE",
          open=[
              "Which method governs every edge case (EDB ruling pending)",
              "Whether public holidays reduce working days",
              "The auditor's confirmed document list",
              "Both are carried in config and reported, never silently resolved",
          ],
          gaps_head="NEXT",
          gaps=[
              "Pilot on one real entity's FY2026 H1 data",
              "Semantic retrieval and the three remaining eval scorers",
              "Run manifest for provable re-runs",
              "Rollout across all participating entities",
          ],
          close="Upload to audit-ready submission — deterministic, evidence-complete, "
                "and entirely on-prem."),
}


# --------------------------------------------------------------------------
# extra slides appended and then moved into place  ·  (spec, target index 0-based)
# --------------------------------------------------------------------------
# The Architecture divider owns three diagrams: the module map fills slide 10,
# these two follow it. python-pptx can only append, so build_final_deck.py moves
# them (see pptx_kit.move_slide).
INSERTS = [
    (S("diagram", key="data_flow",
       kicker="Architecture",
       title="Data flow — one upload to a submission pack"), 10),
    (S("diagram", key="trust_boundary",
       kicker="Architecture",
       title="The LLM proposes, the deterministic engine disposes"), 11),
]
