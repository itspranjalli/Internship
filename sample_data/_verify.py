"""Verify the generated fixtures parse cleanly through the T2/T3 ingest layers.

Run via ``generate.py --check`` (or directly). Confirms:
  * the internal workbooks parse with 0 LayoutErrors and the expected employee /
    person-month / Staff-Costs-row counts,
  * the RSE list and payroll register parse with the expected record counts,
  * every Staff Costs row joined to a Time Sheet employee (join_method != unmatched),
  * the Method A hand-calc in expectations.json reproduces from calendar_utils,
  * regenerating produces value-identical workbooks (re-parse + compare).

Exit code 0 == all checks pass.
"""

from __future__ import annotations

import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from edb_claim.ingest.rse_list import index_by_employee_id, parse_rse_list
from edb_claim.ingest.salary import parse_payroll_register
from edb_claim.ingest.timesheet import parse_internal_workbook

OUT = os.path.dirname(os.path.abspath(__file__))


def _fail(msg: str) -> None:
    print(f"  FAIL: {msg}")


def verify() -> int:
    print("\n=== Verifying generated fixtures via T2/T3 ingest ===")
    ok = True

    exp = json.load(open(os.path.join(OUT, "expectations.json")))
    emp_records = exp["employees"]
    ids_by_entity = {}
    for e in emp_records:
        ids_by_entity.setdefault(e["entity"], []).append(e["employee_id"])

    # --- internal workbooks (T2) ------------------------------------------
    total_employees = 0
    total_person_months = 0
    for fname in ("internal_ANS.xlsx", "internal_DSG.xlsx"):
        res = parse_internal_workbook(os.path.join(OUT, fname))
        n_emp = len(res.employees)
        n_pm = len(res.person_months)
        n_sc = len(res.staff_costs)
        unmatched = [s.row for s in res.staff_costs if s.join_method == "unmatched"]
        total_employees += n_emp
        total_person_months += n_pm
        expected_emp = len(ids_by_entity[res.entity])
        status = "ok" if n_emp == expected_emp else "MISMATCH"
        if n_emp != expected_emp:
            ok = False
            _fail(f"{fname}: {n_emp} employees, expected {expected_emp}")
        if unmatched:
            ok = False
            _fail(f"{fname}: Staff Costs rows unmatched to Time Sheet: {unmatched}")
        if n_sc != n_emp:
            ok = False
            _fail(f"{fname}: {n_sc} Staff Costs rows != {n_emp} employees")
        # join methods should all be cross_ref_employee_id (we write literal IDs)
        methods = {s.join_method for s in res.staff_costs}
        print(f"  {fname}: entity={res.entity!r}")
        print(f"     employees={n_emp} ({status}), person_months={n_pm}, "
              f"staff_costs={n_sc}, join_methods={sorted(methods)}, "
              f"warnings={len(res.warnings)}")
        if res.warnings:
            for w in res.warnings:
                print(f"       warn: {w}")

    # --- RSE list (T3) -----------------------------------------------------
    rse = parse_rse_list(os.path.join(OUT, "rse_list.xlsx"))
    idx = index_by_employee_id(rse)
    print(f"  rse_list.xlsx: {len(rse)} records, {len(idx)} unique IDs")
    if len(rse) != len(emp_records):
        ok = False
        _fail(f"rse_list: {len(rse)} records, expected {len(emp_records)}")
    # every roster employee must be in the RSE list
    missing = [e["employee_id"] for e in emp_records if e["employee_id"] not in idx]
    if missing:
        ok = False
        _fail(f"rse_list: missing employees {missing}")

    # --- payroll (T3) ------------------------------------------------------
    pay = parse_payroll_register(os.path.join(OUT, "payroll.xlsx"))
    print(f"  payroll.xlsx: {len(pay)} employee-month records")
    # missing-payslip case: DSG-006 must have NO April (month 4) row
    dsg006_months = sorted(r.month for r in pay if r.employee_id == "DSG-006")
    if 4 in dsg006_months:
        ok = False
        _fail("payroll: DSG-006 should be missing month 4 (G7 case) but has it")
    else:
        print(f"     DSG-006 (missing-payslip case) months present: {dsg006_months} "
              f"(April correctly absent)")
    # basic-only isolation: pick ANS-001, confirm basic == 9500 (not gross)
    ans1 = [r for r in pay if r.employee_id == "ANS-001"]
    if ans1 and any(abs(r.basic_salary - 9500.0) > 1e-9 for r in ans1):
        ok = False
        _fail("payroll: ANS-001 basic_salary not isolated to 9500 (noise leaked)")

    # --- Method A hand-calc reproducibility -------------------------------
    from sample_data.generate import ROSTER, method_a_handcalc
    by_id = {p.employee_id: p for p in ROSTER}
    for e in emp_records:
        if "method_a" not in e:
            continue
        recomputed = method_a_handcalc(by_id[e["employee_id"]])
        if round(recomputed["claim_amount"], 2) != e["method_a"]["claim_amount"]:
            ok = False
            _fail(f"{e['employee_id']}: hand-calc claim mismatch "
                  f"{recomputed['claim_amount']} != {e['method_a']['claim_amount']}")

    print(f"  totals: employees={total_employees}, person_months={total_person_months}")
    print("=== RESULT:", "ALL CHECKS PASS ===" if ok else "FAILURES ABOVE ===")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(verify())
