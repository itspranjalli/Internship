"""Tests for edb_claim.ingest.timesheet — internal-workbook ingest (PLAN.md T2).

Exercises the parser against the REAL template workbook in ``docs/`` and asserts
the structure it returns (employees, per-month rows, Staff Costs rows with the
workbook's own [A]..[E] values surfaced as-found, and the cross-reference join).

The shipped template is a blank/skeleton workbook: the Time Sheet carries no
Employee ID / Name, and only one cell of monthly hours is populated (W19 = 40,
i.e. October). So the parser legitimately finds exactly one 'real' Time Sheet
row and one person-month; the assertions below pin that observed structure.

Runs under pytest (`.venv/bin/python -m pytest tests/test_timesheet_ingest.py -q`)
OR directly (`python tests/test_timesheet_ingest.py`) via the plain-assert
harness at the bottom.
"""

import os
import sys
from datetime import date

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from edb_claim.domain.models import Citizenship, Employee, EvidenceRef, PersonMonth
from edb_claim.ingest.timesheet import (
    StaffCostsRow,
    parse_internal_workbook,
)

WORKBOOK = os.path.join(
    _REPO_ROOT,
    "docs",
    "AI_COE_Claim_Checklist_Timesheet_for_FY_2026_to_2028_v2_Final.xlsx",
)


def _parse():
    assert os.path.exists(WORKBOOK), f"template workbook missing: {WORKBOOK}"
    return parse_internal_workbook(WORKBOOK)


def test_parses_without_error_and_returns_result():
    res = _parse()
    assert res.file.endswith(".xlsx")
    # Entity name comes from Time Sheet!G3.
    assert res.entity == "ST Engineering Advanced Networks & Sensors Pte Ltd"


def test_time_sheet_real_rows_and_person_months():
    res = _parse()
    # Exactly one row carries identifying content (W19 = 40 hours).
    assert len(res.employees) == 1
    emp = res.employees[0]
    assert isinstance(emp, Employee)
    assert emp.entity == "ST Engineering Advanced Networks & Sensors Pte Ltd"
    assert isinstance(emp.citizenship, Citizenship)

    # One person-month: October (month 10), 40 hours.
    assert len(res.person_months) == 1
    pm = res.person_months[0]
    assert isinstance(pm, PersonMonth)
    assert pm.month == 10
    assert pm.hours == 40.0
    assert pm.employee_id == emp.id

    # Skeleton rows are skipped, not turned into employees.
    assert len(res.skipped_empty_rows) >= 40


def test_every_field_has_evidence_ref():
    res = _parse()
    emp = res.employees[0]
    assert emp.source_refs, "employee must carry EvidenceRefs (FR-7)"
    for r in emp.source_refs:
        assert isinstance(r, EvidenceRef)
        assert r.cell_or_row and r.cell_or_row.startswith("Time Sheet!")
        assert r.file.endswith(".xlsx")

    pm = res.person_months[0]
    assert pm.source_refs[0].cell_or_row == "Time Sheet!W19"

    sc = res.staff_costs[0]
    assert sc.source_refs, "staff-cost row must carry EvidenceRefs (FR-7)"
    labels = {r.label for r in sc.source_refs}
    assert {"actual_salary_a", "e_qualifying_cost"}.issubset(labels)


def test_staff_costs_surfaced_as_found():
    res = _parse()
    assert len(res.staff_costs) >= 1
    sc = res.staff_costs[0]
    assert isinstance(sc, StaffCostsRow)
    assert sc.row == 15
    # Values surfaced verbatim from the workbook's cached cells (NOT recomputed).
    assert sc.actual_salary_a == 10000.0
    assert sc.qualifying_salary_b == 10000
    assert sc.date_join_c1 == date(2026, 1, 1)
    assert sc.date_left_c2 == date(2026, 12, 31)
    assert abs(float(sc.d1_capacity_hours) - 2296.8) < 1e-6
    assert sc.d2_project_hours == 40
    # [E] = [B] * [D3] as the sheet computed it; carried at full precision.
    assert abs(float(sc.e_qualifying_cost) - 174.15534656913968) < 1e-9


def test_cross_reference_join_falls_back_to_row_offset():
    res = _parse()
    sc = res.staff_costs[0]
    # Staff Costs row 15 <-> Time Sheet row 19 (offset 4); cached cross-ref is
    # blank (0) here, so the row-offset fallback must resolve it.
    assert sc.join_method == "row_offset"
    assert sc.employee_id == res.employees[0].id


# --- plain-assert harness (pytest-free) -----------------------------------
if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll {len(fns)} tests passed.")
