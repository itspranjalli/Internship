"""Tests for T3 deterministic ingest: ECMF RSE list + payroll register.

Builds tiny synthetic .xlsx fixtures under ``tests/fixtures/`` with openpyxl
(matching the schemas DEFINED in the ingest modules — the contract T14 must
generate to), parses them, and asserts:

  * RSE list -> correct employee_id / citizenship (G1) / ecmf_validated (G2),
    with foreigners and non-ECMF rows RETAINED (never dropped), each carrying
    an EvidenceRef (FR-7).
  * Payroll -> per-employee-month basic salary ONLY; the CPF/bonus/AWS/
    allowance/gross columns are NOT summed into basic (the core domain rule),
    each SalaryRecord carrying an EvidenceRef to its Basic-Salary cell (FR-7).
  * Determinism: re-parsing yields identical records (PRD §9).

Runs under pytest (`.venv/bin/python -m pytest tests/test_ingest_rse_and_salary.py -q`)
OR directly: `python tests/test_ingest_rse_and_salary.py`.
"""

import os
import sys

from openpyxl import Workbook

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from edb_claim.domain.models import Citizenship, EvidenceRef, SalaryRecord
from edb_claim.ingest.rse_list import (
    parse_rse_list,
    index_by_employee_id,
)
from edb_claim.ingest.salary import (
    parse_payroll_register,
    index_by_employee_month,
)

_FIXTURE_DIR = os.path.join(_REPO_ROOT, "tests", "fixtures")


def _make_rse_fixture() -> str:
    """Write a 4-row ECMF RSE list fixture; return its path."""
    os.makedirs(_FIXTURE_DIR, exist_ok=True)
    path = os.path.join(_FIXTURE_DIR, "rse_list_sample.xlsx")
    wb = Workbook()
    ws = wb.active
    ws.title = "RSE List"
    ws.append(["Employee ID", "Name", "Citizenship", "ECMF Validated"])
    ws.append(["E001", "Tan Wei Ming", "Citizen", "Yes"])     # local + ecmf
    ws.append(["E002", "Siti Nurhaliza", "PR", "TRUE"])       # local(PR) + ecmf
    ws.append(["E003", "John Smith", "Foreigner", "No"])      # foreigner, retained
    ws.append(["E004", "Lim Ah Kow", "Singapore Citizen", "N"])  # local, NOT ecmf
    wb.save(path)
    return path


def _make_payroll_fixture() -> str:
    """Write a payroll register fixture with excluded components; return path.

    Critically: Basic is 6000 but the row carries large CPF/bonus/AWS/allowance/
    gross values. A correct parser stores 6000, never the gross (~10500).
    """
    os.makedirs(_FIXTURE_DIR, exist_ok=True)
    path = os.path.join(_FIXTURE_DIR, "payroll_sample.xlsx")
    wb = Workbook()
    ws = wb.active
    ws.title = "Payroll"
    ws.append(
        [
            "Employee ID", "Name", "Year", "Month", "Basic Salary",
            "Allowances", "Bonus", "AWS", "CPF (Employer)", "CPF (Employee)",
            "Gross Pay",
        ]
    )
    # E001 Jan + Feb 2026. Basic 6000; everything else is noise to be excluded.
    ws.append(["E001", "Tan Wei Ming", 2026, 1, 6000, 500, 2000, 1000, 1020, 1200, 10500])
    ws.append(["E001", "Tan Wei Ming", 2026, 2, 6000, 500, 0, 0, 1020, 1200, 7700])
    # E002 Jan 2026, basic 4800 (will fail G4 later) — exclusions still ignored.
    ws.append(["E002", "Siti Nurhaliza", 2026, 1, 4800, 300, 0, 0, 816, 960, 5100])
    wb.save(path)
    return path


# --------------------------------------------------------------------------
# RSE list tests
# --------------------------------------------------------------------------
def test_rse_list_extracts_all_rows_with_citizenship_and_ecmf():
    recs = parse_rse_list(_make_rse_fixture())
    assert len(recs) == 4, "all 4 rows retained (none dropped)"
    by_id = index_by_employee_id(recs)

    assert by_id["E001"].citizenship is Citizenship.CITIZEN
    assert by_id["E001"].ecmf_validated is True
    assert by_id["E002"].citizenship is Citizenship.PR
    assert by_id["E002"].ecmf_validated is True


def test_rse_list_retains_foreigner_and_non_ecmf_never_dropped():
    by_id = index_by_employee_id(parse_rse_list(_make_rse_fixture()))
    # Foreigner is RETAINED with true status (validate/ excludes it WITH reason).
    assert by_id["E003"].citizenship is Citizenship.FOREIGNER
    assert by_id["E003"].citizenship.is_local is False
    # Local but NOT ECMF-validated — also retained for the G2 cross-check.
    assert by_id["E004"].citizenship is Citizenship.CITIZEN
    assert by_id["E004"].ecmf_validated is False


def test_rse_list_attaches_evidence_ref():
    recs = parse_rse_list(_make_rse_fixture())
    ref = recs[0].source_ref
    assert isinstance(ref, EvidenceRef)
    assert ref.sheet == "RSE List"
    assert ref.cell_or_row == "A2"  # first data row


def test_rse_list_is_deterministic():
    p = _make_rse_fixture()
    assert parse_rse_list(p) == parse_rse_list(p)


# --------------------------------------------------------------------------
# Payroll tests — the core "basic only" guarantee
# --------------------------------------------------------------------------
def test_payroll_basic_only_excludes_cpf_bonus_aws_allowance_gross():
    recs = parse_payroll_register(_make_payroll_fixture())
    idx = index_by_employee_month(recs)

    jan = idx[("E001", 2026, 1)]
    # The row's gross was 10500 with 500+2000+1000+CPF noise. Basic is 6000.
    assert jan.basic_salary == 6000, "must be basic only, NOT gross/total"
    # Explicitly assert the excluded components were not summed in.
    assert jan.basic_salary != 10500
    assert jan.basic_salary < 6000.01

    feb = idx[("E001", 2026, 2)]
    assert feb.basic_salary == 6000


def test_payroll_one_record_per_employee_month():
    recs = parse_payroll_register(_make_payroll_fixture())
    assert len(recs) == 3
    keys = {(r.employee_id, r.year, r.month) for r in recs}
    assert keys == {("E001", 2026, 1), ("E001", 2026, 2), ("E002", 2026, 1)}


def test_payroll_below_floor_value_preserved_not_dropped():
    # 4800 < 5000: ingest must NOT apply G4 (that's validate/'s job) — value kept.
    idx = index_by_employee_month(parse_payroll_register(_make_payroll_fixture()))
    assert idx[("E002", 2026, 1)].basic_salary == 4800


def test_payroll_attaches_evidence_ref_to_basic_cell():
    recs = parse_payroll_register(_make_payroll_fixture())
    ref = recs[0].source_ref
    assert isinstance(ref, EvidenceRef)
    assert ref.sheet == "Payroll"
    assert ref.label == "basic_salary"
    assert ref.cell_or_row == "E2"  # Basic Salary column, first data row


def test_payroll_records_are_salary_records_and_deterministic():
    p = _make_payroll_fixture()
    recs = parse_payroll_register(p)
    assert all(isinstance(r, SalaryRecord) for r in recs)
    assert parse_payroll_register(p) == recs


# --- plain-assert harness (run without pytest) -----------------------------
if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll {len(fns)} tests passed.")
