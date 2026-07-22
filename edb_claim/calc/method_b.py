"""Method B — internal Staff Costs hours-ratio engine (PRD §6, PLAN.md T7).

Replicates the internal ``Staff Costs`` sheet's ``[B]/[D1]/[D2]/[D3]/[E]``
formulas **exactly, including their quirks** — they are surfaced in the variance
report (T8), never "fixed" (CLAUDE.md "replicate as-is, flag in variance, do not
fix").

The formula, verbatim from the sheet (PRD §6 "Method B"):

    [B]  = "N/A" if salary < salary_floor else MIN(salary, salary_cap)
    [D1] = NETWORKDAYS(date_join, date_left) * hours_per_day        (8.8)
    [D2] = project hours over the employment span; New Hire -> "N/A"
    [D3] = 1.0 (100%) if hire_type == New Hire  else  [D2] / [D1]
    [E]  = [B] * [D3]        ("N/A" when [B] is "N/A")
    claim_amount = round([E] * support_rate, 2)

Replicated quirks (each flagged on the result; T8 surfaces them):

  * **New-Hire forced 100% time.** A New Hire gets ``[D3] = 100%`` with NO
    timesheet evidence required (``[D2]`` is "N/A"). This is an audit risk under
    SSRS 4400 (PRD §6 discrepancy #2) and is replicated as-is. Flag:
    ``new_hire_forced_100``.
  * **``[B]`` annual-labelled-but-monthly.** The sheet header calls ``[B]`` the
    "qualifying *annual* salary" but the formula yields a *monthly* capped figure
    (PRD §6 discrepancy #3). Flag: ``b_annual_labelled_but_monthly``.
  * **``[B]`` floor -> "N/A".** Below the floor the *sheet* returns "N/A"
    (whole row drops to "N/A"), which is NOT the same as T5's G4 verdict
    EXCLUSION — we replicate the sheet's arithmetic behaviour here. Flag:
    ``b_below_floor_na``.
  * **Single whole-span ratio.** Unlike Method A's monthly calendar pro-ration,
    Method B is one annual hours ratio (PRD §6 discrepancy #1) — ``[D1]`` spans
    the *whole* employment period (join -> left), ``[D2]`` is the *total* project
    hours, and ``[D3]`` can exceed 100% (the leaver case ANS-003: D3 = 1.103093).
    No clamp is applied — replicated as-is.

This module is DETERMINISTIC and pure Python (PRD §9). It imports NO ``llm/``
code (hard boundary: the LLM never computes claim amounts — CLAUDE.md, PLAN.md
§1). NETWORKDAYS x 8.8 is reused from ``domain.calendar_utils`` — never the
header's raw ``C2 - C1`` (PLAN.md §3 #4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional, Tuple

from edb_claim.config import settings
from edb_claim.domain.calendar_utils import networkdays
from edb_claim.domain.models import (
    HireType,
    MethodBResult,
    MonthlyBreakdownB,
)

# Sentinel the sheet uses for non-applicable cells ([B]/[D2]/[E]).
NA = "N/A"


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MethodBInput:
    """The minimal per-employee facts Method B re-computes from (PRD §6).

    Sourced from the ingest layer — ``hire_type`` from the Time Sheet
    (:class:`~edb_claim.domain.models.Employee`), ``basic_salary`` /
    ``date_join`` / ``date_left`` from the Staff Costs row [A]/[C1]/[C2]
    (:class:`~edb_claim.ingest.timesheet.StaffCostsRow`), and ``project_hours``
    as the total of that employee's monthly Time Sheet hours ([D2]).

    The engine re-computes [B]..[E] from these inputs so it runs on ANY data;
    :func:`reconcile` then checks the re-computed [E] against the workbook's
    surfaced [E] where present.
    """

    employee_id: str
    hire_type: HireType
    basic_salary: float
    date_join: date
    date_left: date
    project_hours: float  # total project hours over the span ([D2] numerator)


# ---------------------------------------------------------------------------
# Result detail (carries the replicated quirks as machine-readable flags for T8)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MethodBDetail:
    """Per-employee Method B breakdown + the quirk flags T8's variance needs.

    Wraps :class:`MethodBResult` (the canonical domain result) and adds the
    raw ``[B]/[D1]/[D2]/[D3]/[E]`` values *as the sheet would show them* (incl.
    "N/A" strings) plus boolean quirk flags so the variance report can surface
    each discrepancy without re-deriving it.
    """

    result: MethodBResult
    # Sheet-faithful cell values (number OR "N/A"), for reconciliation/audit.
    b_value: object        # [B]
    d1_value: float        # [D1] = NETWORKDAYS x 8.8
    d2_value: object       # [D2] (project hours OR "N/A" for New Hire)
    d3_value: float        # [D3]
    e_value: object        # [E] = [B] x [D3] (OR "N/A")
    # Replicated-quirk flags (PRD §6 "Known discrepancies"):
    new_hire_forced_100: bool = False
    b_annual_labelled_but_monthly: bool = False
    b_below_floor_na: bool = False
    d3_over_100: bool = False


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
def compute_method_b(
    inp: MethodBInput,
    *,
    support_rate: Optional[float] = None,
) -> MethodBDetail:
    """Compute Method B for one employee, replicating the Staff Costs sheet.

    ``support_rate`` defaults to ``config.settings.support_rate`` (ASSUMED 30%,
    non-final per PRD §10 Q2). All arithmetic is full-precision; the ONLY
    rounding is the final ``claim_amount = round([E] x support_rate, 2)`` —
    matching the sheet and PRD §6 (no pre-rounding of [E]).
    """
    rate = settings.support_rate if support_rate is None else support_rate

    new_hire = inp.hire_type == HireType.NEW_HIRE

    # [B] = "N/A" if salary < floor else MIN(salary, cap)  (sheet behaviour;
    # the floor here yields "N/A", distinct from T5's G4 EXCLUSION verdict).
    below_floor = inp.basic_salary < settings.salary_floor
    if below_floor:
        b: object = NA
    else:
        b = float(min(inp.basic_salary, settings.salary_cap))

    # [D1] = NETWORKDAYS(join, left) x 8.8  (whole employment span; NOT C2-C1).
    d1 = networkdays(inp.date_join, inp.date_left) * settings.hours_per_day

    # [D2] = project hours; New Hire -> "N/A" (no timesheet hours used).
    d2: object = NA if new_hire else float(inp.project_hours)

    # [D3] = 100% if New Hire (forced, quirk) else [D2] / [D1].
    if new_hire:
        d3 = 1.0  # forced 100% regardless of evidence (replicated, not fixed)
    else:
        d3 = (float(inp.project_hours) / d1) if d1 else 0.0

    # [E] = [B] x [D3]  ("N/A" when [B] is "N/A").
    if b == NA:
        e: object = NA
        qualifying_cost_total = 0.0  # "N/A" -> contributes 0 to a claim
    else:
        e = float(b) * d3
        qualifying_cost_total = float(e)

    # claim = round([E] x support_rate, 2)  (only rounding point — PRD §6).
    claim_amount = round(qualifying_cost_total * rate, 2)

    monthly = (
        MonthlyBreakdownB(
            # Method B is a single whole-span ratio, not a calendar month; we
            # tag the breakdown row with the join year/month for traceability.
            year=inp.date_join.year,
            month=inp.date_join.month,
            b_capped_salary=0.0 if b == NA else float(b),
            d1_capacity_hours=d1,
            d2_project_hours=0.0 if d2 == NA else float(d2),
            d3_time_contribution=d3,
            e_qualifying_cost=qualifying_cost_total,
        ),
    )

    result = MethodBResult(
        employee_id=inp.employee_id,
        qualifying_cost_total=qualifying_cost_total,
        support_rate=rate,
        claim_amount=claim_amount,
        new_hire=new_hire,
        monthly=monthly,
    )

    return MethodBDetail(
        result=result,
        b_value=b,
        d1_value=d1,
        d2_value=d2,
        d3_value=d3,
        e_value=e,
        new_hire_forced_100=new_hire,
        b_annual_labelled_but_monthly=(b != NA),
        b_below_floor_na=below_floor,
        d3_over_100=(d3 > 1.0),
    )


def compute_all(
    inputs: Iterable[MethodBInput],
    *,
    support_rate: Optional[float] = None,
) -> Tuple[MethodBDetail, ...]:
    """Run :func:`compute_method_b` over many employees (order preserved)."""
    return tuple(compute_method_b(i, support_rate=support_rate) for i in inputs)


# ---------------------------------------------------------------------------
# Reconciliation against the workbook's surfaced [E] (T2 StaffCostsRow)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ReconcileResult:
    """Outcome of comparing a re-computed [E] to the workbook's surfaced [E]."""

    employee_id: str
    recomputed_e: object   # our [E] (number OR "N/A")
    workbook_e: object     # the sheet's [E] as ingested (number OR "N/A"/None)
    matched: bool
    note: str = ""


def reconcile(
    detail: MethodBDetail,
    workbook_e: object,
    *,
    tolerance: float = 1e-6,
) -> ReconcileResult:
    """Compare a re-computed [E] against the workbook's surfaced [E] value.

    The workbook value comes from
    :attr:`edb_claim.ingest.timesheet.StaffCostsRow.e_qualifying_cost` (a number
    OR the string "N/A", OR ``None`` when the cell was blank). Numbers are
    compared within ``tolerance`` (full-precision [E], so the gap is float-noise
    only); both-"N/A" matches; a missing workbook value is reported as
    unmatched-because-absent (not an error).
    """
    recomputed = detail.e_value

    # Both "N/A" -> match.
    if recomputed == NA and (workbook_e == NA):
        return ReconcileResult(
            detail.result.employee_id, recomputed, workbook_e, True, "both N/A"
        )

    if workbook_e is None:
        return ReconcileResult(
            detail.result.employee_id, recomputed, workbook_e, False,
            "workbook [E] absent (blank cell)",
        )

    # Mixed N/A vs number -> mismatch.
    if recomputed == NA or workbook_e == NA:
        return ReconcileResult(
            detail.result.employee_id, recomputed, workbook_e, False,
            "one side is N/A, the other numeric",
        )

    try:
        matched = abs(float(recomputed) - float(workbook_e)) <= tolerance
    except (TypeError, ValueError):
        return ReconcileResult(
            detail.result.employee_id, recomputed, workbook_e, False,
            "non-numeric workbook [E] value",
        )
    note = "" if matched else f"delta={float(recomputed) - float(workbook_e):.6f}"
    return ReconcileResult(
        detail.result.employee_id, recomputed, workbook_e, matched, note
    )
