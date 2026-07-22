"""Domain value objects for the EDB RIS(C) claim pipeline (PLAN.md §1).

Data-only: stdlib :mod:`dataclasses` + :mod:`enum`, no business logic and no
I/O (pydantic is intentionally NOT a dependency — T0 standardised on stdlib
frozen dataclasses for clean, dependency-free imports). The calc/output layers
consume these; ingest/validate/llm layers produce them.

Field origins are cited to PRD sections inline. Where a value can originate
from the LLM layer (FR-9→FR-12), an optional ``confidence`` / ``confidence_reason``
pair is carried so nothing is ever discarded and every value can explain itself
(FR-14: "No black box, nothing discarded"). This module only *holds* those
fields; evaluation/threshold logic lives in the llm/ and validate/ layers.

Frozen (immutable) dataclasses are used for pure value objects to support the
determinism guarantee (PRD §9) and safe reuse as dict/set members.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional, Tuple


# ---------------------------------------------------------------------------
# Enums (controlled vocabularies)
# ---------------------------------------------------------------------------
class Citizenship(str, Enum):
    """Local-vs-foreigner status for gate G1 (PRD §6: SG citizen / PR = local).

    Only ``CITIZEN`` and ``PR`` are claimable ("local"); ``FOREIGNER`` fails G1
    and is reported as EXCLUDED, never silently dropped (PRD FR-3).
    """

    CITIZEN = "Citizen"
    PR = "PR"
    FOREIGNER = "Foreigner"

    @property
    def is_local(self) -> bool:
        """Convenience flag (data classification, not business logic): G1 local set."""
        return self in (Citizenship.CITIZEN, Citizenship.PR)


# PRD/PLAN sometimes refer to the local/foreigner split generically.
LocalForeigner = Citizenship


class HireType(str, Enum):
    """Time Sheet hire classification (PRD §6, Method B quirk; List sheet vocab).

    ``NEW_HIRE`` triggers Method B's auto-100% time contribution (``[D3]=100%``)
    — replicated as-is and flagged in the variance report, never "fixed"
    (PRD §6 discrepancy #2, CLAUDE.md).
    """

    NEW_HIRE = "New Hire"
    UPSKILLED = "Upskilled"
    RESKILLED = "Reskilled"


class VerdictStatus(str, Enum):
    """Per-trainee verdict outcome (PRD FR-6)."""

    QUALIFIES = "QUALIFIES"          # all gates pass; row written to EDB output
    EXCLUDED = "EXCLUDED"            # a gate failed (e.g. foreigner, G5 designation)
    BLOCKED = "BLOCKED"             # missing docs prevent a decision (FR-2 blocker)


class GateCode(str, Enum):
    """Eligibility gate identifiers G1-G7 (PRD §6 gate table)."""

    G1 = "G1"  # Local (SG citizen / PR)
    G2 = "G2"  # ECMF-validated RSE
    G3 = "G3"  # Not enjoying another government cash grant
    G4 = "G4"  # Basic monthly salary >= S$5,000 (floor)
    G5 = "G5"  # Designation not in non-qualifying categories
    G6 = "G6"  # Involvement period overlaps claim period
    G7 = "G7"  # Payslip evidence exists for the month


class CalcMethod(str, Enum):
    """The two calculation engines run side-by-side (PRD §6, FR-4)."""

    A = "A"  # EDB monthly pro-ration (presumptive submission basis)
    B = "B"  # Internal Staff Costs hours-ratio method (reconciliation)


# ---------------------------------------------------------------------------
# Evidence pointer (FR-7)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EvidenceRef:
    """Pointer to where a figure came from: ``{source file, sheet, cell/row}``.

    Backs FR-7 one-click traceability and the FR-13 ``evidence_ref`` table:
    "every figure in every claim row resolves to {source file, sheet,
    cell/row}". ``cell_or_row`` holds an Excel cell ("I5"), a row index, or a
    short locator string depending on the source. ``label`` optionally names
    the field (e.g. "basic_salary") for the evidence-pack view.
    """

    file: str                          # source filename (PRD FR-7 {source file})
    sheet: Optional[str] = None        # worksheet name, if tabular (FR-7 {sheet})
    cell_or_row: Optional[str] = None  # "I5" / row index / locator (FR-7 {cell/row})
    label: Optional[str] = None        # which field this ref backs (evidence pack)


# ---------------------------------------------------------------------------
# Core entities
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Employee:
    """A person on an entity's roster (Time Sheet + RSE list; PRD §4, FR-1/FR-3).

    Gate-relevant attributes are stored as plain data; the validate/ layer reads
    them to produce :class:`GateResult` / :class:`Verdict`. ``normalized_name``
    supports FR-11 cross-document name matching ("Tan Wei Ming" vs "WEI MING
    TAN"). LLM-proposed fields (e.g. ``designation`` judged for G5, or a fuzzy
    name match) may carry confidence (FR-10/FR-11, FR-14).
    """

    id: str                                  # employee identifier (FR-13 partition key)
    name: str                                # name as it appears on the Time Sheet
    entity: str                              # participating entity (config.PARTICIPATING_ENTITIES)
    citizenship: Citizenship                 # G1 local/foreigner (PRD §6)
    ecmf_validated: bool                     # G2 ECMF-validated RSE (PRD §6)
    no_other_grant: bool                     # G3 not enjoying another govt cash grant (PRD §6)
    designation: str                         # free-text; judged against G5 set (PRD §6, FR-10)
    hire_type: HireType                      # New Hire / Upskilled / Reskilled (PRD §6)
    normalized_name: Optional[str] = None    # FR-11 reconciliation key
    nric: Optional[str] = None               # canonical NRIC/FIN; a document-lookup key (local-only PII)
    # --- LLM provenance (FR-10/FR-11/FR-14): never discarded, always explainable
    confidence: Optional[float] = None
    confidence_reason: Optional[str] = None
    source_refs: Tuple[EvidenceRef, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SalaryRecord:
    """Basic monthly salary evidence for a person-month (payslip; PRD §4, §6).

    Qualifying salary = **basic monthly salary only** — no CPF, bonus, AWS,
    allowances, COLA, airfare (PRD §6, CLAUDE.md). The cap/floor are applied by
    the calc/validate layers (config.salary_cap / salary_floor), not here.
    LLM-extracted values carry confidence + a plain-language reason (FR-9/FR-14).
    """

    employee_id: str
    year: int
    month: int                               # 1-12
    basic_salary: float                      # basic ONLY (PRD §6)
    source_ref: Optional[EvidenceRef] = None  # payslip location (FR-7)
    confidence: Optional[float] = None        # FR-9 extraction confidence
    confidence_reason: Optional[str] = None   # FR-9/FR-14 plain-language reason


@dataclass(frozen=True)
class PersonMonth:
    """One employee × one month: the unit of eligibility and calculation.

    Gates are evaluated per person-month (PRD §6) and Method A/B retain a full
    monthly breakdown (PRD FR-4). ``hours`` is the month's project hours used by
    ``time_contribution`` (A) and ``[D2]`` (B); ``basic_salary`` is the basic
    monthly figure (PRD §6). Source refs back FR-7 traceability.
    """

    employee_id: str
    year: int
    month: int                               # 1-12
    basic_salary: float                      # basic monthly salary (PRD §6)
    hours: float                             # project hours that month (PRD §6 A/B)
    source_refs: Tuple[EvidenceRef, ...] = field(default_factory=tuple)
    confidence: Optional[float] = None
    confidence_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Validation outputs
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GateResult:
    """Outcome of a single gate G1-G7 for a person(-month) (PRD §6, FR-3).

    ``reason`` is the grounded, source-specific explanation (FR-3/FR-11: "not
    generic error text"). ``source_ref`` points at the value that drove the
    decision (FR-7).
    """

    gate: GateCode
    passed: bool
    reason: Optional[str] = None             # grounded explanation (FR-3/FR-11)
    source_ref: Optional[EvidenceRef] = None  # value that triggered it (FR-7)


@dataclass(frozen=True)
class Verdict:
    """Per-trainee verdict: QUALIFIES / EXCLUDED / BLOCKED (PRD FR-6).

    Lists *every* failed gate and the matching human reasons — foreigners and
    non-qualifying designations are surfaced with reason, never silently dropped
    (PRD FR-3/FR-6). One verdict per person (FR-6).
    """

    employee_id: str
    status: VerdictStatus
    failed_gates: Tuple[GateCode, ...] = field(default_factory=tuple)
    reasons: Tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Calculation results (PRD §6 / FR-4)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MonthlyBreakdownA:
    """Method A per-month components (PRD §6; FR-4 "full monthly breakdown").

    ``qualifying_cost = capped_salary × month_fraction × time_contribution`` is
    carried at full precision (no pre-rounding — PRD §6; only EDB output
    ``I=ROUND(G×H,2)`` rounds).
    """

    year: int
    month: int
    capped_salary: float                     # MIN(basic, cap) (PRD §6)
    month_fraction: float                    # calendar.month_fraction (PRD §6)
    time_contribution: float                 # MIN(1, hours/(weekdays×8.8)) (PRD §6)
    qualifying_cost: float                   # capped×fraction×time, full precision (PRD §6)


@dataclass(frozen=True)
class MethodAResult:
    """Method A (EDB pro-ration) per-employee totals + monthly breakdown (PRD §6).

    ``qualifying_cost_total`` is the sum of monthly ``qualifying_cost`` at full
    precision; ``claim_amount = qualifying_cost_total × support_rate`` (PRD §6,
    support_rate ASSUMED 30% / non-final per config). Breakdown retained per
    FR-4.
    """

    employee_id: str
    qualifying_cost_total: float
    support_rate: float                      # config.support_rate (EDB Support Package: 60%)
    claim_amount: float
    monthly: Tuple[MonthlyBreakdownA, ...] = field(default_factory=tuple)
    months_capped: int = 0                   # months dropped by the upskill 9-month cap (0 = none)


@dataclass(frozen=True)
class MonthlyBreakdownB:
    """Method B per-month components, replicating the Staff Costs sheet (PRD §6).

    Quirks replicated as-is and flagged in variance, NOT fixed (CLAUDE.md):
      * ``time_contribution`` = 100% for New Hire regardless of hours (``[D3]``).
      * ``[B]`` header says "annual" but yields a monthly capped figure.
    ``[D1] = NETWORKDAYS(join, left) × 8.8``; ``[E] = [B] × [D3]``.
    """

    year: int
    month: int
    b_capped_salary: float                   # [B]: N/A if <5000 else MIN(salary,cap)
    d1_capacity_hours: float                 # [D1] = NETWORKDAYS × 8.8
    d2_project_hours: float                  # [D2] project hours
    d3_time_contribution: float              # [D3]: 100% if New Hire else D2/D1
    e_qualifying_cost: float                 # [E] = [B] × [D3], full precision


@dataclass(frozen=True)
class MethodBResult:
    """Method B (internal Staff Costs) per-employee totals + breakdown (PRD §6, FR-4).

    ``new_hire`` propagates the auto-100% quirk so variance can isolate it.
    ``claim_amount = qualifying_cost_total × support_rate`` (PRD §6).
    """

    employee_id: str
    qualifying_cost_total: float             # Σ [E], full precision
    support_rate: float
    claim_amount: float
    new_hire: bool = False                   # drives the variance New-Hire flag (PRD §6 #2)
    monthly: Tuple[MonthlyBreakdownB, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class VarianceRow:
    """Per-employee A-vs-B reconciliation row (PRD §6 discrepancies, FR-4).

    ``new_hire_flag`` highlights New-Hire rows where B>A (no timesheet evidence —
    SSRS 4400 audit risk, PRD §6 #2). The two methods genuinely disagree; this
    surfaces the gap, it does not resolve it (CLAUDE.md, PRD §10 Q1).
    """

    employee_id: str
    amount_a: float                          # MethodAResult.claim_amount
    amount_b: float                          # MethodBResult.claim_amount
    delta_abs: float                         # amount_a - amount_b (or |.|; set by calc)
    delta_pct: Optional[float] = None        # None when amount_a == 0 (div-by-zero)
    new_hire_flag: bool = False              # New-Hire B>A audit-risk flag (PRD §6 #2)
    material: bool = False                   # |delta_pct| > config.variance_material_pct


@dataclass(frozen=True)
class VarianceReport:
    """Aggregate A-vs-B reconciliation across all claimable trainees (PRD §6, FR-4).

    Surfaces the genuine, unresolved disagreement between Method A (EDB
    pro-ration, the submission basis) and Method B (internal Staff Costs) — it
    does NOT pick a winner (ruling pending, PRD §10 Q1; CLAUDE.md). ``rows`` are
    per-employee; the totals sum the two methods' rounded ``claim_amount``s.
    ``new_hire_flagged`` isolates New-Hire rows where B>A (no timesheet evidence,
    SSRS 4400 audit risk — PRD §6 #2); ``materially_divergent`` lists rows past
    the reporting threshold. ``support_rate_is_final`` carries the non-final
    caveat (both amounts use the ASSUMED 30% rate until the LoA confirms).
    """

    rows: Tuple[VarianceRow, ...] = field(default_factory=tuple)
    total_a: float = 0.0
    total_b: float = 0.0
    total_delta_abs: float = 0.0             # total_a - total_b
    total_delta_pct: Optional[float] = None  # None when total_a == 0
    new_hire_flagged: Tuple[str, ...] = field(default_factory=tuple)
    materially_divergent: Tuple[str, ...] = field(default_factory=tuple)
    support_rate_is_final: bool = False      # both amounts non-final until LoA (Q2)
