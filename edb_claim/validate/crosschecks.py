"""Cross-document consistency checks (PRD FR-3; PLAN.md T5).

Cross-checks surface *conflicts between independent sources* — the Time Sheet,
the ECMF RSE list, the payroll register and the Staff Costs sheet — as
**warnings carrying both conflicting values**. They never EXCLUDE or drop anyone
(that is the gates' job, FR-3 "exclusions reported with reasons, never dropped").
A cross-check warning means "two documents disagree, a human should reconcile",
not "this person is ineligible".

Checks implemented (PLAN.md T5 row):

  1. **ECMF flag — Time Sheet vs RSE list.** TS col H vs the authoritative list.
  2. **Hours <= weekday capacity.** Monthly project hours must not exceed
     ``weekdays(month) × 8.8``. Over-capacity is a *warning* (the calc layer
     clamps ``time_contribution`` to 1.0, so the claim is unaffected) — NOT an
     exclusion.
  3. **Payslip basic vs Staff Costs [A].** The payroll basic salary should match
     the Staff Costs actual-monthly-salary [A].
  4. **Join/left dates vs payslip coverage.** Months inside the involvement
     window ``[C1, C2]`` ∩ claim window should have a payslip; a covered month
     with no payslip (or a payslip outside the window) is flagged.

Determinism (PRD §9): pure functions over ingested domain objects; no I/O, no
``datetime.now``/random, **no LLM import**.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import List, Mapping, Optional, Tuple

from edb_claim.config import Config, settings
from edb_claim.domain.calendar_utils import weekdays_in_month
from edb_claim.domain.models import Employee, EvidenceRef, SalaryRecord
from edb_claim.ingest.rse_list import RseListRecord
from edb_claim.ingest.timesheet import StaffCostsRow


class CrossCheckKind(str, Enum):
    """Stable identifiers for the cross-check types (for grouping/reporting)."""

    ECMF_FLAG_CONFLICT = "ecmf_flag_conflict"
    HOURS_OVER_CAPACITY = "hours_over_capacity"
    SALARY_BASIC_VS_STAFF_COSTS_A = "salary_basic_vs_staff_costs_a"
    PAYSLIP_COVERAGE_VS_DATES = "payslip_coverage_vs_dates"


@dataclass(frozen=True)
class CrossCheckWarning:
    """One source-vs-source conflict (FR-3). Carries BOTH conflicting values.

    Never an exclusion: a warning flags a reconciliation item for a human. The
    two sources and their values are recorded verbatim so the conflict is
    auditable (FR-3 "with the conflicting source values").
    """

    kind: CrossCheckKind
    employee_id: str
    message: str
    source_a: Optional[EvidenceRef] = None     # first conflicting source
    value_a: object = None                      # its value
    source_b: Optional[EvidenceRef] = None     # second conflicting source
    value_b: object = None                      # its value
    year: Optional[int] = None                  # person-month context, if any
    month: Optional[int] = None


def _ts_ref(employee: Employee, label: str) -> Optional[EvidenceRef]:
    for r in employee.source_refs:
        if r.label == label:
            return r
    return None


def _sc_ref(staff_cost: Optional[StaffCostsRow], label: str) -> Optional[EvidenceRef]:
    if staff_cost is None:
        return None
    for r in staff_cost.source_refs:
        if r.label == label:
            return r
    return staff_cost.source_refs[0] if staff_cost.source_refs else None


# ---------------------------------------------------------------------------
# 1. ECMF flag: Time Sheet vs RSE list
# ---------------------------------------------------------------------------
def check_ecmf_flag(
    employee: Employee, rse: Optional[RseListRecord]
) -> List[CrossCheckWarning]:
    """Flag a disagreement between the Time Sheet ECMF flag and the RSE list.

    The RSE list is the G2 authority; if the Time Sheet says one thing and the
    list another, that is a data-quality conflict a human must reconcile (the
    gate already decides eligibility off the authority). Agreement -> no warning.
    """
    if rse is None:
        return []
    if employee.ecmf_validated == rse.ecmf_validated:
        return []
    return [
        CrossCheckWarning(
            kind=CrossCheckKind.ECMF_FLAG_CONFLICT,
            employee_id=employee.id,
            message=(
                f"ECMF flag conflict for {employee.id}: Time Sheet says "
                f"{employee.ecmf_validated}, RSE list says {rse.ecmf_validated}. "
                f"RSE list is the G2 authority; reconcile the Time Sheet."
            ),
            source_a=_ts_ref(employee, "ecmf_validated"),
            value_a=employee.ecmf_validated,
            source_b=rse.source_ref,
            value_b=rse.ecmf_validated,
        )
    ]


# ---------------------------------------------------------------------------
# 2. Hours <= weekday capacity (WARNING, not exclusion)
# ---------------------------------------------------------------------------
def check_hours_capacity(
    employee_id: str,
    year: int,
    month: int,
    hours: float,
    source_ref: Optional[EvidenceRef] = None,
    config: Config = settings,
) -> List[CrossCheckWarning]:
    """Flag monthly project hours exceeding ``weekdays(month) × 8.8`` capacity.

    A *warning* only: Method A clamps ``time_contribution`` to 1.0 so the claim
    is unaffected, but hours above the physical weekday capacity signal a
    timesheet data-entry issue worth surfacing (FR-3). ``year``-``month`` is the
    capacity basis; for a year of 0 (Time Sheet stores bare months) the
    configured claim year is used.
    """
    yr = year if year else config.claim_period_start.year
    capacity = weekdays_in_month(yr, month) * config.hours_per_day
    if hours <= capacity:
        return []
    return [
        CrossCheckWarning(
            kind=CrossCheckKind.HOURS_OVER_CAPACITY,
            employee_id=employee_id,
            year=year or None,
            month=month,
            message=(
                f"{employee_id} {yr}-{month:02d}: project hours {hours:g} exceed "
                f"weekday capacity {capacity:g} ({weekdays_in_month(yr, month)} "
                f"weekdays × {config.hours_per_day}). time_contribution clamps to "
                f"1.0 (claim unaffected); verify the timesheet entry."
            ),
            source_a=source_ref,
            value_a=hours,
            value_b=capacity,
        )
    ]


# ---------------------------------------------------------------------------
# 3. Payslip basic vs Staff Costs [A]
# ---------------------------------------------------------------------------
def check_basic_vs_staff_costs_a(
    employee_id: str,
    salary: Optional[SalaryRecord],
    staff_cost: Optional[StaffCostsRow],
    tolerance: float = 0.01,
) -> List[CrossCheckWarning]:
    """Flag a mismatch between a payslip basic salary and Staff Costs [A].

    [A] is the workbook's "actual monthly salary per IR8A"; the payroll basic
    should agree within ``tolerance`` cents. A mismatch is a reconciliation
    warning (which figure feeds the claim is decided by the calc layer off the
    payslip basic), not an exclusion.
    """
    if salary is None or staff_cost is None or staff_cost.actual_salary_a is None:
        return []
    a = float(staff_cost.actual_salary_a)
    if abs(salary.basic_salary - a) <= tolerance:
        return []
    return [
        CrossCheckWarning(
            kind=CrossCheckKind.SALARY_BASIC_VS_STAFF_COSTS_A,
            employee_id=employee_id,
            year=salary.year,
            month=salary.month,
            message=(
                f"{employee_id} {salary.year}-{salary.month:02d}: payslip basic "
                f"{salary.basic_salary:,.2f} != Staff Costs [A] {a:,.2f}. "
                f"Reconcile the salary figures."
            ),
            source_a=salary.source_ref,
            value_a=salary.basic_salary,
            source_b=_sc_ref(staff_cost, "actual_salary_a"),
            value_b=a,
        )
    ]


# ---------------------------------------------------------------------------
# 4. Join/left dates vs payslip coverage
# ---------------------------------------------------------------------------
def _months_in_window(c1: date, c2: date, config: Config) -> List[Tuple[int, int]]:
    """Calendar months in ``[c1, c2]`` ∩ the claim window, as (year, month)."""
    start = max(c1, config.claim_period_start)
    end = min(c2, config.claim_period_end)
    out: List[Tuple[int, int]] = []
    if end < start:
        return out
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        last = calendar.monthrange(y, m)[1]
        if not (date(y, m, last) < start or date(y, m, 1) > end):
            out.append((y, m))
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return out


def check_dates_vs_payslip_coverage(
    employee_id: str,
    staff_cost: Optional[StaffCostsRow],
    salaries: Tuple[SalaryRecord, ...],
    config: Config = settings,
) -> List[CrossCheckWarning]:
    """Flag involvement months with no payslip, and payslips outside the window.

    Each month inside ``[C1, C2]`` ∩ claim window is *expected* to have a payslip;
    a covered month with none, or a payslip dated outside the involvement window,
    is surfaced (FR-3). Missing-payslip months overlap the G7 gate, but this
    cross-check spells out the date-vs-coverage conflict with both sources.
    Open-ended C2 (still employed) is treated as the claim-window end.
    """
    if staff_cost is None or staff_cost.date_join_c1 is None:
        return []
    c1 = staff_cost.date_join_c1
    c2 = staff_cost.date_left_c2 or config.claim_period_end

    have = {(s.year, s.month) for s in salaries}
    warnings: List[CrossCheckWarning] = []

    # 4a. Covered months missing a payslip.
    expected = _months_in_window(c1, c2, config)
    for (y, m) in expected:
        if (y, m) not in have:
            warnings.append(
                CrossCheckWarning(
                    kind=CrossCheckKind.PAYSLIP_COVERAGE_VS_DATES,
                    employee_id=employee_id,
                    year=y,
                    month=m,
                    message=(
                        f"{employee_id} {y}-{m:02d}: involvement "
                        f"{c1.isoformat()}..{c2.isoformat()} covers this month but "
                        f"no payslip is present (coverage-vs-dates conflict)."
                    ),
                    source_a=_sc_ref(staff_cost, "date_join_c1"),
                    value_a=(c1.isoformat(), c2.isoformat()),
                )
            )

    # 4b. Payslips outside the involvement window.
    for s in salaries:
        last = calendar.monthrange(s.year, s.month)[1]
        m_start, m_end = date(s.year, s.month, 1), date(s.year, s.month, last)
        if m_end < c1 or m_start > c2:
            warnings.append(
                CrossCheckWarning(
                    kind=CrossCheckKind.PAYSLIP_COVERAGE_VS_DATES,
                    employee_id=employee_id,
                    year=s.year,
                    month=s.month,
                    message=(
                        f"{employee_id} {s.year}-{s.month:02d}: payslip present but "
                        f"the month falls outside involvement "
                        f"{c1.isoformat()}..{c2.isoformat()} "
                        f"(coverage-vs-dates conflict)."
                    ),
                    source_a=s.source_ref,
                    value_a=f"{s.year}-{s.month:02d}",
                    source_b=_sc_ref(staff_cost, "date_join_c1"),
                    value_b=(c1.isoformat(), c2.isoformat()),
                )
            )
    return warnings


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def run_crosschecks(
    employee: Employee,
    *,
    rse: Optional[RseListRecord] = None,
    staff_cost: Optional[StaffCostsRow] = None,
    salaries: Tuple[SalaryRecord, ...] = (),
    monthly_hours: Mapping[int, float] = None,
    monthly_hours_refs: Mapping[int, EvidenceRef] = None,
    config: Config = settings,
) -> List[CrossCheckWarning]:
    """Run every cross-check for one ``employee`` and collect the warnings.

    ``salaries`` are this employee's payslip records (any months). ``monthly_hours``
    maps month-number -> project hours (from the Time Sheet) for the capacity
    check; ``monthly_hours_refs`` supplies the matching EvidenceRefs. Nothing is
    ever dropped — only warnings are returned (FR-3).
    """
    monthly_hours = monthly_hours or {}
    monthly_hours_refs = monthly_hours_refs or {}
    warnings: List[CrossCheckWarning] = []

    warnings.extend(check_ecmf_flag(employee, rse))

    for month, hours in sorted(monthly_hours.items()):
        warnings.extend(
            check_hours_capacity(
                employee.id,
                config.claim_period_start.year,
                month,
                hours,
                monthly_hours_refs.get(month),
                config,
            )
        )

    for s in salaries:
        warnings.extend(
            check_basic_vs_staff_costs_a(employee.id, s, staff_cost)
        )

    warnings.extend(
        check_dates_vs_payslip_coverage(employee.id, staff_cost, salaries, config)
    )
    return warnings
