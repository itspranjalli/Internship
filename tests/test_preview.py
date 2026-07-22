"""Tests for the evidence-preview helpers (edb_claim.app.preview).

Pure logic only (no Streamlit): citation-filename -> real path resolution, cell-ref
parsing, and reading a window of a real sample worksheet with the focus cell located.
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from edb_claim.app.preview import (
    excel_sheet_to_grid,
    parse_cell_ref,
    resolve_evidence_path,
)

_SAMPLE = os.path.join(_REPO_ROOT, "sample_data")
_PAYROLL = os.path.join(_SAMPLE, "payroll.xlsx")


def test_parse_cell_ref_variants():
    assert parse_cell_ref("Time Sheet!G19") == ("Time Sheet", 7, 19)
    assert parse_cell_ref("I5") == (None, 9, 5)
    assert parse_cell_ref("A2") == (None, 1, 2)
    assert parse_cell_ref("AA3") == (None, 27, 3)
    assert parse_cell_ref("row 19") == (None, None, 19)
    assert parse_cell_ref("") == (None, None, None)
    assert parse_cell_ref(None) == (None, None, None)


def test_resolve_path_exact_and_registry():
    # exact path wins
    assert resolve_evidence_path(_PAYROLL) == _PAYROLL
    # basename via registry (simulates an upload saved under a temp name)
    reg = {"payroll.xlsx": _PAYROLL, "edb_abc.xlsx": _PAYROLL}
    assert resolve_evidence_path("payroll.xlsx", reg) == _PAYROLL
    assert resolve_evidence_path("some/dir/edb_abc.xlsx", reg) == _PAYROLL
    # unknown -> None
    assert resolve_evidence_path("nope.xlsx", reg) is None
    assert resolve_evidence_path("", reg) is None


def test_excel_window_locates_focus_cell():
    grid = excel_sheet_to_grid(_PAYROLL, focus_col=5, focus_row=2)  # E2
    assert grid.sheet_name
    assert grid.focus_row == 2 and grid.focus_col_letter == "E"
    assert 2 in grid.row_numbers and "E" in grid.col_letters
    # the grid is non-empty and rectangular
    assert grid.rows and all(len(r) == len(grid.col_letters) for r in grid.rows)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"ok   {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1; print(f"FAIL {fn.__name__}: {exc}")
    sys.exit(1 if failed else 0)
