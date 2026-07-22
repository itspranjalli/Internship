"""Document completeness matrix (PRD FR-2; PLAN.md T4).

Builds the **employee × month × required-document** matrix for one claim
period, classifies every cell ``present`` / ``missing`` / ``inconsistent``, and
grades every missing/inconsistent item ``BLOCKER`` or ``WARNING`` per the FR-2
severity table. Per-employee and per-entity rollups give a blocker/warning
count and a plain-language summary that feeds FR-8 (HR readiness view) and
FR-14 (transparency).

This layer is **deterministic and side-effect-free** (CLAUDE.md, PRD §9): it
reads already-ingested domain objects and returns a result object; it never
mutates global state, never writes, and **never imports the LLM layer**. It
does no claim arithmetic — it only checks presence/consistency of evidence.

Severity table (PRD FR-2; ASSUMED pending Q4 auditor doc list)
--------------------------------------------------------------
================================================  =================  ========
Document / condition                              Scope              Severity
================================================  =================  ========
Payslip for the claimed month                     per person-month   BLOCKER  (G7)
ECMF-validated RSE list                           per entity (once)  BLOCKER  (G2 input)
Internal Timesheet / Staff Costs workbook         per entity (once)  BLOCKER
EDB blank output template                         per entity (once)  BLOCKER
Leave report                                      per entity/period  WARNING
CPF / bank statement                              per person         WARNING
Timesheet hours > weekday capacity                per person-month   WARNING
Payslip basic ≠ Staff Costs [A]                   per person-month   WARNING
================================================  =================  ========

Beyond this core set, the system also presence-checks the wider HR evidence
checklist an officer assembles per UEN (completed RISC submission form, Letter of
Award, skill-validation list, trainee list, AI artifacts, CPF/bank statements,
PL3 confirmation, training certification, signed monthly progress report, daily
clocking — all WARNINGs). These are **never parsed**, are opt-in
(no cell unless their presence is supplied), and their severities are ASSUMED
pending the auditor's confirmed document list (PRD §10 Q4). See ``DOC_LABEL``.

Scope decisions (which docs are per-person-month vs per-entity-once)
--------------------------------------------------------------------
  * **Per person-month:** the *payslip* (one per employee per claimed month).
    The set of "claimed months" for a person = the months in the claim window
    for which the Time Sheet carries hours (so a person who only appears in
    Mar–Jun is only expected to have Mar–Jun payslips, never Jan/Feb). This is
    the matrix that drives the BLOCKER count.
  * **Per person (presence only):** CPF / bank statement — checked for presence
    once per employee, never per month, never parsed (§4). WARNING if absent.
  * **Per entity, once:** ECMF-validated RSE list, the internal Timesheet/Staff
    Costs workbook, the EDB blank output template, and the leave report. These
    are recorded as a single entity-scoped row each, not duplicated across the
    matrix. The first three are BLOCKERs (no roster / no hours input / no output
    target); the leave report is a WARNING (informational hours plausibility).
  * **Per person-month conditions (not documents):** hours > weekday capacity,
    and payslip-basic ≠ Staff Costs [A]. Both are WARNINGs surfaced for audit
    review; neither blocks the claim (the cap clamp / variance handle them).

Incremental re-run (DoD-2)
--------------------------
:func:`build_completeness` is pure: given updated inputs it recomputes from
scratch, but because each cell is classified independently the previously
blocked cell clears as soon as the re-uploaded payslip is present, and no
unrelated cell changes. :func:`reapply_salary` is a convenience that returns a
*new* result reflecting an added/updated payslip set without re-reading any
other input — the same matrix object can be threaded through the HR re-upload
loop and only the affected cells flip. Nothing is mutated in place.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from enum import Enum
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from edb_claim.config import settings as _default_settings
from edb_claim.config import Config
from edb_claim.domain.models import EvidenceRef
from edb_claim.ingest.rse_list import RseListRecord
from edb_claim.ingest.salary import SalaryRecord
from edb_claim.ingest.timesheet import IngestResult, StaffCostsRow


# ---------------------------------------------------------------------------
# Controlled vocabularies
# ---------------------------------------------------------------------------
class CellStatus(str, Enum):
    """State of one matrix cell (PRD FR-2: present / missing / inconsistent)."""

    PRESENT = "present"           # required evidence is there and consistent
    MISSING = "missing"           # required evidence absent
    INCONSISTENT = "inconsistent"  # present but conflicts with another source


class Severity(str, Enum):
    """How serious a missing/inconsistent item is (PRD FR-2 severity table)."""

    BLOCKER = "BLOCKER"  # claim row suppressed until fixed
    WARNING = "WARNING"  # claimable, flagged for audit
    NONE = "NONE"        # present/consistent — nothing to report


class DocType(str, Enum):
    """The required documents / conditions checked by FR-2.

    The first block (payslip … payslip≠staff-costs) is the original POC set that
    drives the BLOCKER count and the calculation. The second block is the wider
    HR evidence checklist (the documents an HR officer actually assembles per
    UEN); these are **presence-checked only** in the POC — never parsed — and are
    all WARNINGs except the completed RISC submission form, which gates the
    submission for that UEN. Severities/scopes here are ASSUMED pending the
    auditor's confirmed document list (PRD §10 Q4).
    """

    PAYSLIP = "payslip"                          # per person-month, BLOCKER
    CPF_BANK = "cpf_bank_statement"             # DEPRECATED alias (kept for back-compat)
    ECMF_RSE_LIST = "ecmf_rse_list"             # per entity once, BLOCKER
    INTERNAL_WORKBOOK = "internal_workbook"     # per entity once, BLOCKER
    EDB_TEMPLATE = "edb_output_template"        # per entity once, BLOCKER
    LEAVE_REPORT = "leave_report"               # per entity/period, WARNING
    HOURS_OVER_CAPACITY = "hours_over_capacity"  # per person-month condition, WARNING
    PAYSLIP_NE_STAFF_COSTS_A = "payslip_ne_staff_costs_a"  # per p-month, WARNING

    # --- wider HR evidence checklist (presence-checked; ASSUMED severities) ---
    # Entity-once documents
    RISC_SUBMISSION_FORM = "risc_submission_form"  # per UEN once, WARNING (approval already granted)
    LETTER_OF_AWARD = "letter_of_award"            # per entity once, WARNING (sets support rate)
    SKILL_VALIDATION_LIST = "skill_validation_list"  # per entity once, WARNING
    TRAINEE_LIST = "trainee_list"                  # per entity once, WARNING (emp no + train dates)
    AI_ARTIFACTS = "ai_artifacts"                  # per entity once, WARNING (codebase/app)
    # Per-person documents
    CPF_STATEMENT = "cpf_statement"                # per person presence, WARNING
    BANK_STATEMENT = "bank_statement"              # per person presence, WARNING (proof of payment)
    PL3_CONFIRMATION = "pl3_confirmation"          # per person presence, WARNING
    TRAINING_CERTIFICATION = "training_certification"  # per person presence, WARNING (CLT/ext.)
    MONTHLY_PROGRESS_REPORT = "monthly_progress_report"  # per person presence, WARNING (signed)
    DAILY_CLOCKING = "daily_clocking"              # per person presence, WARNING (actual days)


class DocScope(str, Enum):
    """Scope at which a document/condition is required (see module docstring)."""

    PERSON_MONTH = "person_month"
    PERSON = "person"
    ENTITY = "entity"


# Static severity assignment for a *missing or inconsistent* item (PRD FR-2).
# Present cells always resolve to Severity.NONE regardless of this table.
SEVERITY_TABLE: Mapping[DocType, Severity] = {
    DocType.PAYSLIP: Severity.BLOCKER,
    DocType.ECMF_RSE_LIST: Severity.BLOCKER,
    DocType.INTERNAL_WORKBOOK: Severity.BLOCKER,
    DocType.EDB_TEMPLATE: Severity.BLOCKER,
    DocType.CPF_BANK: Severity.WARNING,
    DocType.LEAVE_REPORT: Severity.WARNING,
    DocType.HOURS_OVER_CAPACITY: Severity.WARNING,
    DocType.PAYSLIP_NE_STAFF_COSTS_A: Severity.WARNING,
    # wider HR evidence checklist (ASSUMED — PRD §10 Q4)
    # RISC submission form demoted to WARNING: EDB approval already granted, so
    # the form is no longer a precondition to prepare this claim.
    DocType.RISC_SUBMISSION_FORM: Severity.WARNING,
    DocType.LETTER_OF_AWARD: Severity.WARNING,
    DocType.SKILL_VALIDATION_LIST: Severity.WARNING,
    DocType.TRAINEE_LIST: Severity.WARNING,
    DocType.AI_ARTIFACTS: Severity.WARNING,
    DocType.CPF_STATEMENT: Severity.WARNING,
    DocType.BANK_STATEMENT: Severity.WARNING,
    DocType.PL3_CONFIRMATION: Severity.WARNING,
    DocType.TRAINING_CERTIFICATION: Severity.WARNING,
    DocType.MONTHLY_PROGRESS_REPORT: Severity.WARNING,
    DocType.DAILY_CLOCKING: Severity.WARNING,
}

DOC_SCOPE: Mapping[DocType, DocScope] = {
    DocType.PAYSLIP: DocScope.PERSON_MONTH,
    DocType.HOURS_OVER_CAPACITY: DocScope.PERSON_MONTH,
    DocType.PAYSLIP_NE_STAFF_COSTS_A: DocScope.PERSON_MONTH,
    DocType.CPF_BANK: DocScope.PERSON,
    DocType.ECMF_RSE_LIST: DocScope.ENTITY,
    DocType.INTERNAL_WORKBOOK: DocScope.ENTITY,
    DocType.EDB_TEMPLATE: DocScope.ENTITY,
    DocType.LEAVE_REPORT: DocScope.ENTITY,
    # wider HR evidence checklist
    DocType.RISC_SUBMISSION_FORM: DocScope.ENTITY,
    DocType.LETTER_OF_AWARD: DocScope.ENTITY,
    DocType.SKILL_VALIDATION_LIST: DocScope.ENTITY,
    DocType.TRAINEE_LIST: DocScope.ENTITY,
    DocType.AI_ARTIFACTS: DocScope.ENTITY,
    DocType.CPF_STATEMENT: DocScope.PERSON,
    DocType.BANK_STATEMENT: DocScope.PERSON,
    DocType.PL3_CONFIRMATION: DocScope.PERSON,
    DocType.TRAINING_CERTIFICATION: DocScope.PERSON,
    DocType.MONTHLY_PROGRESS_REPORT: DocScope.PERSON,
    DocType.DAILY_CLOCKING: DocScope.PERSON,
}

# Human-readable labels for the wider HR evidence checklist (UI + reasons).
DOC_LABEL: Mapping[DocType, str] = {
    DocType.RISC_SUBMISSION_FORM: "completed RISC submission form",
    DocType.LETTER_OF_AWARD: "EDB Letter of Award / offer letter",
    DocType.SKILL_VALIDATION_LIST: "skill validation list",
    DocType.TRAINEE_LIST: "list of trainees (employee no. + training dates)",
    DocType.AI_ARTIFACTS: "supporting AI artifacts (codebase / app)",
    DocType.CPF_STATEMENT: "CPF statement",
    DocType.BANK_STATEMENT: "bank statement (proof of payment)",
    DocType.PL3_CONFIRMATION: "formal PL3 status confirmation",
    DocType.TRAINING_CERTIFICATION: "training certification with start/end dates",
    DocType.MONTHLY_PROGRESS_REPORT: "monthly progress report (signed by supervisor)",
    DocType.DAILY_CLOCKING: "daily clocking record (actual days on AI COE project)",
}

# Tolerance for the payslip-basic vs Staff Costs [A] money comparison (cents).
_MONEY_EPS = 0.005


# ---------------------------------------------------------------------------
# Result objects (immutable; the public API surface)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MatrixCell:
    """One employee × (month) × document cell of the FR-2 matrix.

    ``severity`` is ``NONE`` when ``status`` is PRESENT; otherwise it is the
    fixed severity for ``doc_type`` from :data:`SEVERITY_TABLE`. ``month`` is
    ``None`` for non-person-month-scoped documents. ``reason`` is a grounded,
    source-specific plain-language explanation (FR-2/FR-14, never generic).
    """

    employee_id: Optional[str]      # None for entity-scoped rows
    entity: str
    doc_type: DocType
    scope: DocScope
    status: CellStatus
    severity: Severity
    month: Optional[int] = None     # 1-12 for person-month cells, else None
    reason: str = ""
    source_ref: Optional[EvidenceRef] = None

    @property
    def is_blocker(self) -> bool:
        return self.severity is Severity.BLOCKER and self.status is not CellStatus.PRESENT

    @property
    def is_warning(self) -> bool:
        return self.severity is Severity.WARNING and self.status is not CellStatus.PRESENT


@dataclass(frozen=True)
class EmployeeRollup:
    """Per-employee blocker/warning rollup + plain-language summary (FR-2/FR-8)."""

    employee_id: str
    entity: str
    name: str
    blocker_count: int
    warning_count: int
    ready: bool                       # True iff zero blockers
    summary: str                      # plain-language ("ready" / "blocked — missing April payslip")
    blocker_cells: Tuple[MatrixCell, ...] = field(default_factory=tuple)
    warning_cells: Tuple[MatrixCell, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class EntityRollup:
    """Per-entity rollup for the HR readiness view (FR-2/FR-8/FR-14)."""

    entity: str
    employee_count: int
    ready_count: int
    blocked_count: int
    blocker_count: int                # total blocker cells (entity + person)
    warning_count: int                # total warning cells
    summary: str                      # "12 of 14 ready; 2 blocked — missing March payslip"
    entity_cells: Tuple[MatrixCell, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CompletenessResult:
    """Full FR-2 completeness output for one entity's claim period.

    Side-effect-free value object: cells + rollups, no I/O. ``cells`` holds
    every matrix cell (entity, person, and person-month scopes) so the UI/db
    layers can render the matrix and the evidence index can trace each one.
    """

    entity: str
    claim_year: int
    claim_months: Tuple[int, ...]
    cells: Tuple[MatrixCell, ...]
    employees: Tuple[EmployeeRollup, ...]
    rollup: EntityRollup

    # --- convenience accessors -------------------------------------------
    def employee(self, employee_id: str) -> Optional[EmployeeRollup]:
        for e in self.employees:
            if e.employee_id == employee_id:
                return e
        return None

    @property
    def blocker_cells(self) -> Tuple[MatrixCell, ...]:
        return tuple(c for c in self.cells if c.is_blocker)

    @property
    def warning_cells(self) -> Tuple[MatrixCell, ...]:
        return tuple(c for c in self.cells if c.is_warning)

    def cells_for(self, employee_id: str) -> Tuple[MatrixCell, ...]:
        return tuple(c for c in self.cells if c.employee_id == employee_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_MONTH_NAME: Tuple[str, ...] = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def _claim_months(config: Config) -> Tuple[int, Tuple[int, ...]]:
    """Return (claim_year, months) for the POC single-year claim window.

    The POC claim window (config.claim_period) is within a single calendar year
    (2026-01-01 → 2026-06-30). We assert single-year so the per-month matrix has
    an unambiguous year key; a multi-year window would need a (year, month) key
    and is out of scope for the POC (PRD §10 Q7).
    """
    start, end = config.claim_period
    if start.year != end.year:
        raise ValueError(
            f"completeness: POC assumes a single-year claim window; got "
            f"{start} → {end}. Extend to (year, month) keys for multi-year."
        )
    months = tuple(range(start.month, end.month + 1))
    return start.year, months


def _expected_payslip_months(
    ts: IngestResult, employee_id: str, claim_months: Sequence[int]
) -> Tuple[int, ...]:
    """Months (within the claim window) for which a payslip is *expected*.

    A payslip is expected for a person-month iff the Time Sheet carries hours
    for that month (the person was on the project), restricted to the claim
    window. The Time Sheet stores bare months (year=0); we intersect with the
    claim window's months. Returned sorted & de-duplicated for determinism.
    """
    months = {
        pm.month
        for pm in ts.person_months
        if pm.employee_id == employee_id and pm.month in claim_months
    }
    return tuple(sorted(months))


def _staff_costs_a_by_employee(
    ts: IngestResult,
) -> Mapping[str, Optional[float]]:
    """employee_id -> Staff Costs [A] actual monthly salary (or None)."""
    out: Dict[str, Optional[float]] = {}
    for sc in ts.staff_costs:  # type: StaffCostsRow
        if sc.employee_id:
            out[sc.employee_id] = sc.actual_salary_a
    return out


def _capacity_hours(year: int, month: int, config: Config) -> float:
    """Weekday capacity for a month = weekdays × hours_per_day (PRD §6 note 1)."""
    # Local import keeps the module import graph minimal and avoids any cycle.
    from edb_claim.domain.calendar_utils import weekdays_in_month

    return weekdays_in_month(year, month) * config.hours_per_day


def _summarize_employee(
    name: str,
    blocker_cells: Sequence[MatrixCell],
    warning_cells: Sequence[MatrixCell],
) -> str:
    """Plain-language per-employee summary (FR-2/FR-14, grounded)."""
    if not blocker_cells and not warning_cells:
        return "ready — all required documents present"
    parts: List[str] = []
    if blocker_cells:
        parts.append("BLOCKED: " + "; ".join(c.reason for c in blocker_cells))
    if warning_cells:
        parts.append("warnings: " + "; ".join(c.reason for c in warning_cells))
    return " | ".join(parts)


def _summarize_entity(
    entity: str,
    employees: Sequence[EmployeeRollup],
    entity_cells: Sequence[MatrixCell],
) -> str:
    """Entity readiness summary, e.g. '12 of 14 ready; 2 blocked — ...'."""
    total = len(employees)
    ready = sum(1 for e in employees if e.ready)
    blocked = total - ready

    entity_blockers = [c for c in entity_cells if c.is_blocker]
    if entity_blockers:
        # An entity-level blocker (missing RSE list / workbook / template) gates
        # the whole entity — surface it up front.
        head = (
            f"{entity}: ENTITY BLOCKED — "
            + "; ".join(c.reason for c in entity_blockers)
        )
        return head

    if total == 0:
        return f"{entity}: no employees in claim period."

    base = f"{ready} of {total} ready"
    if blocked == 0:
        return f"{base} — no blockers."
    # Append the distinct blocker reasons for the blocked employees.
    reasons: List[str] = []
    for e in employees:
        if not e.ready:
            for c in e.blocker_cells:
                if c.reason not in reasons:
                    reasons.append(c.reason)
    return f"{base}; {blocked} blocked — " + "; ".join(reasons)


# ---------------------------------------------------------------------------
# Cell builders
# ---------------------------------------------------------------------------
def _entity_doc_cells(
    entity: str,
    *,
    rse_list_present: bool,
    internal_workbook_present: bool,
    edb_template_present: bool,
    leave_report_present: bool,
    rse_list_ref: Optional[EvidenceRef],
    workbook_ref: Optional[EvidenceRef],
    extra_entity_docs: Mapping[DocType, Optional[bool]],
) -> List[MatrixCell]:
    """One cell per entity-scoped document.

    The four core docs (RSE list, workbook, EDB template, leave report) are
    always emitted. ``extra_entity_docs`` carries the wider per-UEN checklist
    (completed RISC submission form, Letter of Award, skill-validation list,
    trainee list, AI artifacts); each is opt-in — emitted only when its presence
    is ``True``/``False``, skipped when ``None`` (untracked this run).
    """
    spec = (
        (DocType.ECMF_RSE_LIST, rse_list_present, rse_list_ref,
         "ECMF-validated RSE list"),
        (DocType.INTERNAL_WORKBOOK, internal_workbook_present, workbook_ref,
         "internal Timesheet/Staff Costs workbook"),
        (DocType.EDB_TEMPLATE, edb_template_present, None,
         "EDB blank output template"),
        (DocType.LEAVE_REPORT, leave_report_present, None,
         "leave report"),
    )
    cells: List[MatrixCell] = []
    for doc, present, ref, label in spec:
        severity = SEVERITY_TABLE[doc]
        if present:
            cells.append(
                MatrixCell(
                    employee_id=None, entity=entity, doc_type=doc,
                    scope=DocScope.ENTITY, status=CellStatus.PRESENT,
                    severity=Severity.NONE,
                    reason=f"{label} provided.", source_ref=ref,
                )
            )
        else:
            cells.append(
                MatrixCell(
                    employee_id=None, entity=entity, doc_type=doc,
                    scope=DocScope.ENTITY, status=CellStatus.MISSING,
                    severity=severity,
                    reason=f"{label} not provided for {entity}.",
                )
            )

    # wider per-UEN checklist (opt-in, fixed order for determinism)
    for doc in (
        DocType.RISC_SUBMISSION_FORM, DocType.LETTER_OF_AWARD,
        DocType.SKILL_VALIDATION_LIST, DocType.TRAINEE_LIST, DocType.AI_ARTIFACTS,
    ):
        present = extra_entity_docs.get(doc)
        if present is None:
            continue
        label = DOC_LABEL[doc]
        if present:
            cells.append(
                MatrixCell(
                    employee_id=None, entity=entity, doc_type=doc,
                    scope=DocScope.ENTITY, status=CellStatus.PRESENT,
                    severity=Severity.NONE, reason=f"{label} provided for {entity}.",
                )
            )
        else:
            cells.append(
                MatrixCell(
                    employee_id=None, entity=entity, doc_type=doc,
                    scope=DocScope.ENTITY, status=CellStatus.MISSING,
                    severity=SEVERITY_TABLE[doc],
                    reason=f"{label} not provided for {entity}.",
                )
            )
    return cells


def _person_cells(
    *,
    employee_id: str,
    entity: str,
    name: str,
    claim_year: int,
    expected_months: Sequence[int],
    salary_by_month: Mapping[int, SalaryRecord],
    hours_by_month: Mapping[int, float],
    staff_costs_a: Optional[float],
    cpf_bank_present: bool,
    person_docs: Mapping[DocType, Optional[bool]],
    config: Config,
) -> List[MatrixCell]:
    """All cells for one employee: payslip per month + conditions + evidence docs.

    ``person_docs`` carries the wider per-person HR evidence checklist (PL3
    confirmation, training certification, signed monthly progress report, daily
    clocking). Each value is ``True`` (present), ``False`` (missing → WARNING),
    or absent/``None`` (not tracked this run → no cell emitted, so the matrix is
    unchanged when HR isn't supplying these yet).
    """
    cells: List[MatrixCell] = []

    # --- payslip per expected person-month (BLOCKER if missing) ----------
    for month in expected_months:
        rec = salary_by_month.get(month)
        mname = _MONTH_NAME[month - 1]
        if rec is not None:
            cells.append(
                MatrixCell(
                    employee_id=employee_id, entity=entity,
                    doc_type=DocType.PAYSLIP, scope=DocScope.PERSON_MONTH,
                    status=CellStatus.PRESENT, severity=Severity.NONE,
                    month=month,
                    reason=f"{mname} {claim_year} payslip present for {employee_id}.",
                    source_ref=rec.source_ref,
                )
            )
        else:
            cells.append(
                MatrixCell(
                    employee_id=employee_id, entity=entity,
                    doc_type=DocType.PAYSLIP, scope=DocScope.PERSON_MONTH,
                    status=CellStatus.MISSING, severity=Severity.BLOCKER,
                    month=month,
                    reason=(
                        f"missing {mname} payslip for {employee_id} "
                        f"({name}) — no salary evidence for that month (G7)."
                    ),
                )
            )

        # --- hours > weekday capacity (WARNING) --------------------------
        hours = hours_by_month.get(month)
        if hours is not None:
            cap = _capacity_hours(claim_year, month, config)
            if hours > cap + 1e-9:
                cells.append(
                    MatrixCell(
                        employee_id=employee_id, entity=entity,
                        doc_type=DocType.HOURS_OVER_CAPACITY,
                        scope=DocScope.PERSON_MONTH,
                        status=CellStatus.INCONSISTENT, severity=Severity.WARNING,
                        month=month,
                        reason=(
                            f"{mname} hours {hours:g} exceed weekday capacity "
                            f"{cap:g} ({employee_id}); time contribution clamps "
                            f"to 100% — flagged for audit."
                        ),
                    )
                )

        # --- payslip basic != Staff Costs [A] (WARNING) ------------------
        if rec is not None and staff_costs_a is not None:
            if abs(rec.basic_salary - staff_costs_a) > _MONEY_EPS:
                cells.append(
                    MatrixCell(
                        employee_id=employee_id, entity=entity,
                        doc_type=DocType.PAYSLIP_NE_STAFF_COSTS_A,
                        scope=DocScope.PERSON_MONTH,
                        status=CellStatus.INCONSISTENT, severity=Severity.WARNING,
                        month=month,
                        reason=(
                            f"{mname} payslip basic {rec.basic_salary:g} != "
                            f"Staff Costs [A] {staff_costs_a:g} for {employee_id} "
                            f"— cross-check mismatch, surfaced for review."
                        ),
                        source_ref=rec.source_ref,
                    )
                )

    # --- per-person presence-checked evidence (all WARNINGs) -------------
    # CPF and bank are split (the bank statement is the proof of payment the
    # SSRS 4400 auditor needs); both are driven by the existing presence flag in
    # the POC. The remaining checklist docs come from ``person_docs`` and are
    # opt-in (no cell when untracked). Order is fixed for determinism.
    person_doc_presence: List[Tuple[DocType, Optional[bool]]] = [
        (DocType.CPF_STATEMENT, cpf_bank_present),
        (DocType.BANK_STATEMENT, cpf_bank_present),
        (DocType.PL3_CONFIRMATION, person_docs.get(DocType.PL3_CONFIRMATION)),
        (DocType.TRAINING_CERTIFICATION, person_docs.get(DocType.TRAINING_CERTIFICATION)),
        (DocType.MONTHLY_PROGRESS_REPORT, person_docs.get(DocType.MONTHLY_PROGRESS_REPORT)),
        (DocType.DAILY_CLOCKING, person_docs.get(DocType.DAILY_CLOCKING)),
    ]
    for doc, present in person_doc_presence:
        if present is None:
            continue  # not tracked this run — leave the matrix untouched
        label = DOC_LABEL[doc]
        if present:
            cells.append(
                MatrixCell(
                    employee_id=employee_id, entity=entity, doc_type=doc,
                    scope=DocScope.PERSON, status=CellStatus.PRESENT,
                    severity=Severity.NONE,
                    reason=f"{label} present for {employee_id}.",
                )
            )
        else:
            cells.append(
                MatrixCell(
                    employee_id=employee_id, entity=entity, doc_type=doc,
                    scope=DocScope.PERSON, status=CellStatus.MISSING,
                    severity=SEVERITY_TABLE[doc],
                    reason=(
                        f"{label} not provided for {employee_id} ({name}); "
                        f"presence-checked only — flagged, not blocking."
                    ),
                )
            )

    return cells


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def build_completeness(
    timesheet: IngestResult,
    salary_records: Sequence[SalaryRecord],
    rse_records: Sequence[RseListRecord],
    *,
    edb_template_present: bool = True,
    leave_report_present: bool = False,
    cpf_bank_present_ids: Optional[Sequence[str]] = None,
    entity_docs: Optional[Mapping[DocType, Optional[bool]]] = None,
    person_docs: Optional[Mapping[DocType, Optional[bool]]] = None,
    config: Optional[Config] = None,
) -> CompletenessResult:
    """Build the FR-2 completeness matrix for one entity's claim period.

    Pure and side-effect-free: reads ingested domain objects, returns a
    :class:`CompletenessResult`. Does no claim arithmetic and never imports the
    LLM layer (CLAUDE.md). Determinism (PRD §9): cells/rollups are emitted in a
    stable order (employees in Time Sheet order, months ascending).

    Args:
        timesheet: parsed internal workbook for ONE entity (T2 ``IngestResult``).
            Provides the employee roster, expected payslip months (months with
            hours in the claim window), and Staff Costs [A] for the cross-check.
        salary_records: parsed payroll records (T3); the per-person-month
            payslip evidence. May span multiple entities — filtered by the
            timesheet roster's employee ids.
        rse_records: parsed ECMF RSE list (T3). A non-empty list with at least
            one roster employee present means "the ECMF-validated RSE list was
            provided" (entity-once BLOCKER doc). Citizenship/ECMF *validity* is
            G1/G2's job (T5), not completeness — FR-2 only checks presence.
        edb_template_present: whether the EDB blank output template was uploaded
            for this entity (entity-once BLOCKER). Defaults True (the POC ships
            the template); set False to surface the missing-template blocker.
        leave_report_present: whether a leave report was uploaded (entity WARNING).
        cpf_bank_present_ids: employee ids that have a CPF/bank statement on file
            (presence only, never parsed — §4). Ids not listed get a WARNING.
            ``None`` => treat all as present (the POC has no CPF/bank fixtures,
            so absence would be noise); pass ``()`` to flag all employees. Drives
            both the CPF-statement and bank-statement (proof-of-payment) cells.
        entity_docs: optional presence of the wider per-UEN checklist documents
            keyed by :class:`DocType` (``RISC_SUBMISSION_FORM``, ``LETTER_OF_AWARD``,
            ``SKILL_VALIDATION_LIST``, ``TRAINEE_LIST``, ``AI_ARTIFACTS``). Each
            value is ``True``/``False``/``None``; ``None`` (or omitted) means "not
            tracked this run" and emits no cell — so the matrix is unchanged when
            HR isn't yet supplying these. All are WARNINGs (the RISC submission
            form is presence-checked, not a blocker — EDB approval already granted).
        person_docs: optional presence of the wider per-person checklist documents
            keyed by :class:`DocType` (``PL3_CONFIRMATION``, ``TRAINING_CERTIFICATION``,
            ``MONTHLY_PROGRESS_REPORT``, ``DAILY_CLOCKING``), applied uniformly to
            every rostered employee. Same ``True``/``False``/``None`` opt-in rule;
            all WARNINGs.
        config: tunables (claim window, hours/day). Defaults to the package
            ``settings``.

    Returns:
        A :class:`CompletenessResult` with every matrix cell and the per-employee
        / per-entity rollups.
    """
    cfg = config or _default_settings
    claim_year, claim_months = _claim_months(cfg)

    entity = timesheet.entity or ""
    roster = list(timesheet.employees)  # Time Sheet order (determinism)
    roster_ids = {e.id for e in roster}

    # --- entity-once document presence -----------------------------------
    # The ECMF RSE list is "provided" iff at least one roster employee appears
    # in it. (An empty/foreign-only list with no roster overlap => not provided.)
    rse_ids = {r.employee_id for r in rse_records}
    rse_list_present = bool(roster_ids & rse_ids)
    rse_list_ref = rse_records[0].source_ref if rse_records else None
    # The internal workbook is "provided" iff it yielded a roster.
    internal_workbook_present = bool(roster)
    workbook_ref = (
        EvidenceRef(file=timesheet.file, sheet="Time Sheet", label="internal_workbook")
        if timesheet.file
        else None
    )

    # --- per-person-month payslip index (this entity's roster only) ------
    # (employee_id -> {month -> SalaryRecord}) for the claim year & window.
    salary_index: Dict[str, Dict[int, SalaryRecord]] = {}
    for rec in salary_records:
        if rec.employee_id not in roster_ids:
            continue
        if rec.year != claim_year or rec.month not in claim_months:
            continue
        salary_index.setdefault(rec.employee_id, {})[rec.month] = rec

    # --- per-person-month hours index ------------------------------------
    hours_index: Dict[str, Dict[int, float]] = {}
    for pm in timesheet.person_months:
        if pm.employee_id not in roster_ids or pm.month not in claim_months:
            continue
        hours_index.setdefault(pm.employee_id, {})[pm.month] = pm.hours

    staff_costs_a = _staff_costs_a_by_employee(timesheet)

    cpf_present = (
        roster_ids if cpf_bank_present_ids is None else set(cpf_bank_present_ids)
    )
    entity_docs = dict(entity_docs or {})
    person_docs = dict(person_docs or {})

    # --- entity-scoped cells ---------------------------------------------
    entity_cells = _entity_doc_cells(
        entity,
        rse_list_present=rse_list_present,
        internal_workbook_present=internal_workbook_present,
        edb_template_present=edb_template_present,
        leave_report_present=leave_report_present,
        rse_list_ref=rse_list_ref,
        workbook_ref=workbook_ref,
        extra_entity_docs=entity_docs,
    )

    # --- per-employee cells + rollups ------------------------------------
    all_cells: List[MatrixCell] = list(entity_cells)
    emp_rollups: List[EmployeeRollup] = []

    for emp in roster:
        expected = _expected_payslip_months(timesheet, emp.id, claim_months)
        cells = _person_cells(
            employee_id=emp.id,
            entity=entity,
            name=emp.name,
            claim_year=claim_year,
            expected_months=expected,
            salary_by_month=salary_index.get(emp.id, {}),
            hours_by_month=hours_index.get(emp.id, {}),
            staff_costs_a=staff_costs_a.get(emp.id),
            cpf_bank_present=emp.id in cpf_present,
            person_docs=person_docs,
            config=cfg,
        )
        all_cells.extend(cells)

        blockers = tuple(c for c in cells if c.is_blocker)
        warnings = tuple(c for c in cells if c.is_warning)
        emp_rollups.append(
            EmployeeRollup(
                employee_id=emp.id,
                entity=entity,
                name=emp.name,
                blocker_count=len(blockers),
                warning_count=len(warnings),
                ready=len(blockers) == 0,
                summary=_summarize_employee(emp.name, blockers, warnings),
                blocker_cells=blockers,
                warning_cells=warnings,
            )
        )

    # --- entity rollup ----------------------------------------------------
    entity_blockers = sum(1 for c in entity_cells if c.is_blocker)
    entity_warnings = sum(1 for c in entity_cells if c.is_warning)
    total_blockers = entity_blockers + sum(e.blocker_count for e in emp_rollups)
    total_warnings = entity_warnings + sum(e.warning_count for e in emp_rollups)
    ready_count = sum(1 for e in emp_rollups if e.ready)

    rollup = EntityRollup(
        entity=entity,
        employee_count=len(emp_rollups),
        ready_count=ready_count,
        blocked_count=len(emp_rollups) - ready_count,
        blocker_count=total_blockers,
        warning_count=total_warnings,
        summary=_summarize_entity(entity, emp_rollups, entity_cells),
        entity_cells=tuple(entity_cells),
    )

    return CompletenessResult(
        entity=entity,
        claim_year=claim_year,
        claim_months=claim_months,
        cells=tuple(all_cells),
        employees=tuple(emp_rollups),
        rollup=rollup,
    )


# ---------------------------------------------------------------------------
# Incremental re-run (DoD-2)
# ---------------------------------------------------------------------------
def reapply_salary(
    result: CompletenessResult,
    timesheet: IngestResult,
    updated_salary_records: Sequence[SalaryRecord],
    rse_records: Sequence[RseListRecord],
    **kwargs,
) -> CompletenessResult:
    """Re-run completeness after a payslip re-upload (FR-2 re-upload loop).

    Convenience wrapper for the HR re-upload loop: pass the *new* full salary
    set (e.g. the original plus the re-uploaded April payslip) and get a fresh
    :class:`CompletenessResult`. Because :func:`build_completeness` classifies
    each cell independently, the previously-blocked cell clears and no unrelated
    cell changes (DoD-2). The original ``result`` is **not mutated** — a new
    object is returned. ``result`` is accepted for an explicit, readable
    call-site even though the recompute is from the supplied inputs.
    """
    # ``result`` documents intent (the prior state being superseded); the pure
    # recompute below is what guarantees no unrelated cell flips.
    _ = result
    return build_completeness(
        timesheet,
        updated_salary_records,
        rse_records,
        **kwargs,
    )
