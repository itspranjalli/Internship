"""Eligibility gates G1-G7, evaluated per person-month (PRD §6, FR-3; PLAN.md T5).

Each gate returns a :class:`~edb_claim.domain.models.GateResult`
``(gate, passed, reason, source_ref)`` with a *grounded* reason (the specific
source value that drove the decision — never generic error text, FR-3) and an
:class:`~edb_claim.domain.models.EvidenceRef` to where that value came from
(FR-7). Failed gates are **reported, never silently dropped** (CLAUDE.md / FR-3):
the caller (T9 verdict engine) assembles every failed gate into a verdict.

Determinism (PRD §9): pure functions over already-ingested domain objects;
no I/O, no ``datetime.now``/random, **no LLM import** (the calc/validate layers
must run with the model offline — CLAUDE.md). G5 is a deterministic
case-insensitive membership test here; borderline designations are *flagged for
review* (``GateEvaluation.needs_review``) rather than hard-failed, and T17's
FR-10 LLM judging refines exactly those flagged cases later.

Gate semantics (PRD §6 gate table):

==== ===================================================== ============================
Gate Rule                                                  Source of record
==== ===================================================== ============================
G1   Local (SG citizen / PR)                               RSE list (authority) + TS col E
G2   ECMF-validated RSE                                    RSE list (authority) + TS col H
G3   Not enjoying another government cash grant            TS col I (TRUE = compliant)
G4   Basic monthly salary >= floor (EXCLUSION gate)        Payslip
G5   Designation not in non-qualifying categories          TS col G
G6   Involvement period overlaps claim period              Staff Costs C1/C2
G7   Payslip evidence exists for the month                 Document check
==== ===================================================== ============================

The 20,000 **cap** is deliberately NOT a gate — it is an arithmetic clamp the
calc layer applies to a *retained* person-month (PRD §6). Only the 5,000
**floor** excludes (G4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Tuple

from edb_claim.config import Config, settings
from edb_claim.domain.models import (
    Citizenship,
    Employee,
    EvidenceRef,
    GateCode,
    GateResult,
    PersonMonth,
    SalaryRecord,
)
from edb_claim.ingest.rse_list import RseListRecord
from edb_claim.ingest.timesheet import StaffCostsRow

# Ordered list of the gates, for stable iteration / reporting (PRD §9).
GATE_ORDER: Tuple[GateCode, ...] = (
    GateCode.G1,
    GateCode.G2,
    GateCode.G3,
    GateCode.G4,
    GateCode.G5,
    GateCode.G6,
    GateCode.G7,
)


@dataclass(frozen=True)
class GateEvaluation:
    """A :class:`GateResult` plus the deterministic-review flag (PLAN.md T5).

    ``needs_review`` marks a result the deterministic layer is **not confident
    enough to settle alone** — currently only borderline G5 designations
    (FR-10). The result is NOT hard-failed (it passes as a best-effort match);
    T17's LLM designation judging refines the flagged cases and may overturn the
    provisional ``passed`` value. Everything else carries ``needs_review=False``.
    """

    result: GateResult
    needs_review: bool = False

    # Convenience pass-throughs (read-only views of the wrapped result).
    @property
    def gate(self) -> GateCode:
        return self.result.gate

    @property
    def passed(self) -> bool:
        return self.result.passed

    @property
    def reason(self) -> Optional[str]:
        return self.result.reason

    @property
    def source_ref(self) -> Optional[EvidenceRef]:
        return self.result.source_ref


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _ts_ref(employee: Employee, label: str) -> Optional[EvidenceRef]:
    """Find the Time Sheet EvidenceRef the ingest tagged with ``label`` (FR-7)."""
    for r in employee.source_refs:
        if r.label == label:
            return r
    return None


def _eval(
    gate: GateCode,
    passed: bool,
    reason: str,
    source_ref: Optional[EvidenceRef],
    needs_review: bool = False,
) -> GateEvaluation:
    return GateEvaluation(
        result=GateResult(
            gate=gate, passed=passed, reason=reason, source_ref=source_ref
        ),
        needs_review=needs_review,
    )


def _month_bounds(year: int, month: int) -> Tuple[date, date]:
    import calendar as _cal

    last = _cal.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def _ranges_overlap(a0: date, a1: date, b0: date, b1: date) -> bool:
    return a0 <= b1 and b0 <= a1


# ---------------------------------------------------------------------------
# Individual gates
# ---------------------------------------------------------------------------
def gate_g1_local(
    employee: Employee, rse: Optional[RseListRecord]
) -> GateEvaluation:
    """G1 — Local (SG citizen / PR). RSE list is the authority; TS col E backs it.

    Authority precedence: the ECMF-validated RSE list (PRD §4 "authoritative
    roster of qualifying RSEs + citizenship/PR status"). The Time Sheet
    Local/Foreigner cell is the secondary source used only when the RSE list has
    no row for this employee (the cross-check in crosschecks.py surfaces any
    *disagreement* between the two). Foreigners are reported EXCLUDED with reason,
    never dropped (FR-3).
    """
    if rse is not None:
        citizenship = rse.citizenship
        source = rse.source_ref
        src_label = "RSE list"
    else:
        citizenship = employee.citizenship
        source = _ts_ref(employee, "citizenship")
        src_label = "Time Sheet col E (no RSE-list row)"

    passed = citizenship.is_local
    if passed:
        reason = f"Local ({citizenship.value}) per {src_label}."
    else:
        reason = (
            f"Not a local ({citizenship.value}) per {src_label} -> fails G1; "
            f"only SG citizens / PRs are claimable."
        )
    return _eval(GateCode.G1, passed, reason, source)


def gate_g2_ecmf(
    employee: Employee, rse: Optional[RseListRecord]
) -> GateEvaluation:
    """G2 — ECMF-validated RSE. RSE list authority + Time Sheet col H.

    The person passes only when ECMF-validated. The RSE list is the authority;
    when it has no row, the Time Sheet ECMF flag is used (and crosschecks.py
    surfaces any TS-vs-list conflict). Non-ECMF rows are reported, never dropped.
    """
    if rse is not None:
        validated = rse.ecmf_validated
        source = rse.source_ref
        src_label = "RSE list"
    else:
        validated = employee.ecmf_validated
        source = _ts_ref(employee, "ecmf_validated")
        src_label = "Time Sheet col H (no RSE-list row)"

    if validated:
        reason = f"ECMF-validated per {src_label}."
    else:
        reason = f"Not ECMF-validated per {src_label} -> fails G2."
    return _eval(GateCode.G2, validated, reason, source)


def gate_g3_no_other_grant(employee: Employee) -> GateEvaluation:
    """G3 — Not enjoying another government cash grant (Time Sheet col I).

    Polarity note (PRD §6): col I is the HR *confirmation* that the RSE is **not**
    enjoying another grant, so TRUE = compliant (gate passes). FALSE means the
    person IS on another grant -> fails G3.
    """
    compliant = employee.no_other_grant
    source = _ts_ref(employee, "no_other_grant")
    if compliant:
        reason = "Confirmed not enjoying another government cash grant (col I = TRUE)."
    else:
        reason = (
            "Enjoying another government cash grant (col I = FALSE) -> fails G3."
        )
    return _eval(GateCode.G3, compliant, reason, source)


def gate_g4_salary_floor(
    salary: Optional[SalaryRecord],
    config: Config = settings,
) -> GateEvaluation:
    """G4 — Basic monthly salary >= floor (EXCLUSION gate; PRD §6).

    The 5,000 *floor* is a hard exclusion: a person-month whose basic monthly
    salary is below it is EXCLUDED. This is distinct from the 20,000 *cap*, which
    is an arithmetic clamp the calc layer applies to a retained person-month and
    is NOT gated here.

    When no payslip is present we cannot assert the floor; G4 is reported failed
    with a "no salary evidence" reason (G7 is the primary blocker for that month,
    but G4 must not silently pass an unproven salary — conservative per FR-3).
    """
    floor = config.salary_floor
    if salary is None:
        reason = (
            f"No basic-salary evidence for this month; cannot confirm >= floor "
            f"{floor:,} (G4 unverifiable — see G7)."
        )
        return _eval(GateCode.G4, False, reason, None)

    basic = salary.basic_salary
    passed = basic >= floor
    if passed:
        reason = f"Basic monthly salary {basic:,.0f} >= floor {floor:,} (G4)."
    else:
        reason = (
            f"Basic monthly salary {basic:,.0f} < floor {floor:,} (G4) -> EXCLUDED."
        )
    return _eval(GateCode.G4, passed, reason, salary.source_ref)


def gate_g5_designation(
    employee: Employee, config: Config = settings
) -> GateEvaluation:
    """G5 — Designation NOT in the non-qualifying set (PRD §6; FR-10 later).

    Deterministic, case-insensitive matching against
    ``config.non_qualifying_designations`` (Marketing, Finance, Sales, HR, Admin,
    Facilities Mgmt, Legal). Matching strategy:

      * **Exact (normalised) equality** OR a non-qualifying term appearing as a
        whole word in the designation (so "HR Manager" -> HR, "Sales Lead" ->
        Sales) -> hard FAIL with a grounded reason.
      * A **clearly engineering/technical** designation -> PASS, no review.
      * Anything else that is neither a clean match nor clearly technical (e.g.
        "Engineering Operations Manager", which contains the ambiguous word
        "Operations"/"Manager") -> PASS provisionally **and flagged for review**
        (``needs_review=True``). The deterministic layer does not hard-fail
        borderline titles; T17's LLM judging refines them (FR-10).

    Blank designation -> flagged for review (cannot judge G5 without a title).
    """
    source = _ts_ref(employee, "designation")
    raw = (employee.designation or "").strip()
    norm = " ".join(raw.lower().split())
    tokens = set(norm.replace("/", " ").replace("&", " ").split())

    if not raw:
        return _eval(
            GateCode.G5,
            True,
            "Designation is blank; cannot judge G5 deterministically -> review.",
            source,
            needs_review=True,
        )

    # 1) Non-qualifying match (exact normalised equality or whole-word hit).
    for bad in config.non_qualifying_designations:
        bad_norm = " ".join(bad.lower().split())
        bad_tokens = bad_norm.split()
        whole_word_hit = all(t in tokens for t in bad_tokens)
        if norm == bad_norm or whole_word_hit:
            reason = (
                f"Designation {raw!r} matches non-qualifying category {bad!r} "
                f"-> fails G5."
            )
            return _eval(GateCode.G5, False, reason, source)

    # 2) Clearly technical / engineering titles -> clean pass.
    _TECH_TERMS = {
        "engineer",
        "engineering",
        "scientist",
        "science",
        "developer",
        "researcher",
        "research",
        "data",
        "ai",
        "ml",
        "robotics",
        "software",
        "mlops",
        "architect",
        "analyst",
    }
    if tokens & _TECH_TERMS:
        # Even technical titles can carry an ambiguous managerial qualifier
        # (e.g. "Engineering Operations Manager"); flag those for review while
        # still passing, so T17 can confirm the role is hands-on technical.
        ambiguous = bool(tokens & {"manager", "operations", "lead", "head", "director"})
        reason = (
            f"Designation {raw!r} reads as a technical/engineering role "
            f"(not in the non-qualifying set) -> passes G5"
            + (" (borderline managerial qualifier -> review)." if ambiguous else ".")
        )
        return _eval(GateCode.G5, True, reason, source, needs_review=ambiguous)

    # 3) Neither a clean non-qualifying match nor clearly technical -> review.
    reason = (
        f"Designation {raw!r} is not in the non-qualifying set but is not "
        f"clearly technical -> passes G5 provisionally, flagged for review (FR-10)."
    )
    return _eval(GateCode.G5, True, reason, source, needs_review=True)


def gate_g6_involvement_overlap(
    year: int,
    month: int,
    staff_cost: Optional[StaffCostsRow],
    config: Config = settings,
) -> GateEvaluation:
    """G6 — Involvement period overlaps the claim period (Staff Costs C1/C2).

    Uses the person's involvement window ``[C1 date_join, C2 date_left]`` from
    the Staff Costs row and tests overlap with the **specific person-month**
    (``year``-``month``) intersected with the configured claim window. A
    person-month outside the involvement window fails G6 (they were not employed
    on the project that month).

    When the Staff Costs row / dates are missing, G6 is reported unverifiable
    (failed with a clear reason) rather than silently passing.
    """
    m_start, m_end = _month_bounds(year, month)
    claim_start, claim_end = config.claim_period
    # The month must itself sit inside the claim window to be claimable.
    win_start = max(m_start, claim_start)
    win_end = min(m_end, claim_end)

    if staff_cost is None or staff_cost.date_join_c1 is None:
        reason = (
            f"No involvement dates (Staff Costs C1/C2) available for "
            f"{year}-{month:02d}; cannot confirm overlap with the claim period "
            f"-> G6 unverifiable."
        )
        src = staff_cost.source_refs[0] if (staff_cost and staff_cost.source_refs) else None
        return _eval(GateCode.G6, False, reason, src)

    join = staff_cost.date_join_c1
    # An open-ended (still-employed) record may leave C2 blank -> treat as the
    # claim-window end so the person remains in-period.
    left = staff_cost.date_left_c2 or claim_end

    src = next(
        (r for r in staff_cost.source_refs if r.label == "date_join_c1"),
        staff_cost.source_refs[0] if staff_cost.source_refs else None,
    )

    if win_end < win_start:
        # The month is entirely outside the configured claim window.
        reason = (
            f"{year}-{month:02d} is outside the claim window "
            f"{claim_start.isoformat()}..{claim_end.isoformat()} -> fails G6."
        )
        return _eval(GateCode.G6, False, reason, src)

    overlaps = _ranges_overlap(join, left, win_start, win_end)
    if overlaps:
        reason = (
            f"Involvement {join.isoformat()}..{left.isoformat()} overlaps "
            f"{year}-{month:02d} within the claim period (G6)."
        )
    else:
        reason = (
            f"Involvement {join.isoformat()}..{left.isoformat()} does not cover "
            f"{year}-{month:02d} -> fails G6 for this person-month."
        )
    return _eval(GateCode.G6, overlaps, reason, src)


def gate_g7_payslip_present(
    year: int, month: int, salary: Optional[SalaryRecord]
) -> GateEvaluation:
    """G7 — Payslip evidence exists for the month (document check).

    Passes when a :class:`SalaryRecord` (payslip) is present for this exact
    person-month; otherwise fails as a blocker for the month (the verdict engine
    maps a missing-doc G7 failure to BLOCKED rather than EXCLUDED — FR-2/FR-6).
    """
    if salary is None:
        reason = (
            f"No payslip evidence for {year}-{month:02d} -> fails G7 (claim "
            f"blocked for this person-month pending re-upload)."
        )
        return _eval(GateCode.G7, False, reason, None)
    reason = f"Payslip present for {year}-{month:02d} (G7)."
    return _eval(GateCode.G7, True, reason, salary.source_ref)


# ---------------------------------------------------------------------------
# Orchestration: all gates for one person-month
# ---------------------------------------------------------------------------
def evaluate_person_month(
    employee: Employee,
    person_month: PersonMonth,
    *,
    rse: Optional[RseListRecord] = None,
    salary: Optional[SalaryRecord] = None,
    staff_cost: Optional[StaffCostsRow] = None,
    config: Config = settings,
) -> Tuple[GateEvaluation, ...]:
    """Evaluate G1-G7 for one ``employee`` × ``person_month`` (PRD §6, FR-3).

    The ``year``/``month`` come from ``person_month``. ``rse``/``salary``/
    ``staff_cost`` are the matched ingest records for this person(-month); pass
    ``None`` when a source is genuinely absent and the relevant gate reports it
    unverifiable rather than silently passing.

    Returns the gate evaluations in :data:`GATE_ORDER` (stable for determinism).
    """
    year, month = person_month.year, person_month.month
    return (
        gate_g1_local(employee, rse),
        gate_g2_ecmf(employee, rse),
        gate_g3_no_other_grant(employee),
        gate_g4_salary_floor(salary, config),
        gate_g5_designation(employee, config),
        gate_g6_involvement_overlap(year, month, staff_cost, config),
        gate_g7_payslip_present(year, month, salary),
    )


def failed_gates(evaluations: Tuple[GateEvaluation, ...]) -> List[GateEvaluation]:
    """The subset that did not pass — what the verdict engine reports (FR-3/FR-6).

    Never drops anyone: a person-month with any failed gate is surfaced with the
    gate + grounded reason + source ref attached, for EXCLUDED/BLOCKED handling.
    """
    return [e for e in evaluations if not e.passed]
