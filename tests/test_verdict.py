"""Tests for edb_claim.validate.verdict — the FR-6 verdict engine (T9).

Pins the QUALIFIES / EXCLUDED / BLOCKED decision and its precedence
(EXCLUDED > BLOCKED > QUALIFIES), mirroring the §8 oracle cases:

  * substantive gate fail (G1/G2/G3/G4-below-floor/G5/G6-no-overlap) -> EXCLUDED;
  * missing payslip (G7) or unverifiable G4/G6 (no source) -> BLOCKED;
  * all gates pass (warnings / borderline-but-passing G5) -> QUALIFIES.

Also checks: exclusion beats a co-occurring block; completeness blockers drive
BLOCKED; every failed gate + grounded reason is carried (never dropped);
ordering/dedup; determinism; and the validate/ ↛ llm/ import boundary. One
integration test drives the real gate functions to validate the ``source_ref``
convention the classifier relies on.

Runs under pytest OR directly via the plain-assert harness at the bottom.
"""

import ast
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from edb_claim.domain.models import (
    Citizenship,
    Employee,
    EvidenceRef,
    GateCode,
    GateResult,
    HireType,
    SalaryRecord,
    VerdictStatus,
)
from edb_claim.validate.completeness import EmployeeRollup
from edb_claim.validate.gates import (
    GateEvaluation,
    gate_g1_local,
    gate_g4_salary_floor,
    gate_g7_payslip_present,
)
from edb_claim.validate.verdict import compute_verdict, compute_verdicts


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
_REF = EvidenceRef(file="ts.xlsx", sheet="Time Sheet", cell_or_row="E19", label="x")


def _ev(gate, passed, *, source=None, reason="r", needs_review=False):
    return GateEvaluation(
        result=GateResult(gate=gate, passed=passed, reason=reason, source_ref=source),
        needs_review=needs_review,
    )


def _all_pass(**overrides):
    """Seven passing gate evaluations (one per gate), with optional overrides."""
    evals = {g: _ev(g, True, source=_REF) for g in GateCode}
    evals.update(overrides)
    return list(evals.values())


def _rollup(blocker_count, *, summary="blocked — missing April payslip"):
    return EmployeeRollup(
        employee_id="E",
        entity="ent",
        name="N",
        blocker_count=blocker_count,
        warning_count=0,
        ready=(blocker_count == 0),
        summary=summary,
    )


# ---------------------------------------------------------------------------
# 1. The three outcomes
# ---------------------------------------------------------------------------
def test_all_gates_pass_qualifies():
    v = compute_verdict("ANS-001", _all_pass())
    assert v.status is VerdictStatus.QUALIFIES
    assert v.failed_gates == ()
    assert v.reasons == ()


def test_substantive_gate_fail_excludes():
    """DSG-002 shape: foreigner -> G1 fail with a source -> EXCLUDED."""
    evals = _all_pass(**{GateCode.G1: _ev(GateCode.G1, False, source=_REF, reason="foreigner")})
    v = compute_verdict("DSG-002", evals)
    assert v.status is VerdictStatus.EXCLUDED
    assert v.failed_gates == (GateCode.G1,)
    assert "foreigner" in v.reasons[0]


def test_missing_payslip_g7_blocks():
    """DSG-006 shape: G7 fails (no payslip, source None) -> BLOCKED."""
    evals = _all_pass(**{GateCode.G7: _ev(GateCode.G7, False, source=None, reason="no payslip 2026-04")})
    v = compute_verdict("DSG-006", evals)
    assert v.status is VerdictStatus.BLOCKED
    assert v.failed_gates == (GateCode.G7,)


def test_g4_below_floor_excludes_but_g4_unverifiable_blocks():
    """G4 fail with a source = below floor (EXCLUDED); without = unverifiable (BLOCKED)."""
    below = _all_pass(**{GateCode.G4: _ev(GateCode.G4, False, source=_REF, reason="below floor")})
    assert compute_verdict("X", below).status is VerdictStatus.EXCLUDED

    unverifiable = _all_pass(**{GateCode.G4: _ev(GateCode.G4, False, source=None, reason="no salary")})
    assert compute_verdict("X", unverifiable).status is VerdictStatus.BLOCKED


# ---------------------------------------------------------------------------
# 2. Precedence: EXCLUDED > BLOCKED > QUALIFIES
# ---------------------------------------------------------------------------
def test_exclusion_beats_block():
    """Foreigner AND missing payslip -> EXCLUDED (no point chasing docs)."""
    evals = _all_pass(**{
        GateCode.G1: _ev(GateCode.G1, False, source=_REF, reason="foreigner"),
        GateCode.G7: _ev(GateCode.G7, False, source=None, reason="no payslip"),
    })
    v = compute_verdict("X", evals)
    assert v.status is VerdictStatus.EXCLUDED
    # both failures still reported, ordered by GATE_ORDER (G1 before G7).
    assert v.failed_gates == (GateCode.G1, GateCode.G7)


def test_completeness_blocker_drives_block_and_carries_summary():
    """All gates pass but the rollup has a blocker cell -> BLOCKED + summary reason."""
    v = compute_verdict("X", _all_pass(), rollup=_rollup(1))
    assert v.status is VerdictStatus.BLOCKED
    assert any("April payslip" in r for r in v.reasons)


def test_exclusion_beats_doc_blocker():
    evals = _all_pass(**{GateCode.G5: _ev(GateCode.G5, False, source=_REF, reason="HR Manager")})
    v = compute_verdict("X", evals, rollup=_rollup(2))
    assert v.status is VerdictStatus.EXCLUDED


def test_clean_rollup_does_not_block():
    v = compute_verdict("X", _all_pass(), rollup=_rollup(0))
    assert v.status is VerdictStatus.QUALIFIES


# ---------------------------------------------------------------------------
# 3. Reporting: never drop, order, dedup
# ---------------------------------------------------------------------------
def test_failed_gates_deduped_and_ordered_across_months():
    """G7 fails in two months + G2 fails once -> distinct codes in GATE_ORDER."""
    evals = _all_pass() + [
        _ev(GateCode.G7, False, source=None, reason="no payslip 2026-04"),
        _ev(GateCode.G7, False, source=None, reason="no payslip 2026-05"),
        _ev(GateCode.G2, False, source=_REF, reason="not ECMF"),
    ]
    # remove the passing G2/G7 so only failures remain for those codes
    evals = [e for e in evals if not (e.passed and e.gate in (GateCode.G2, GateCode.G7))]
    v = compute_verdict("X", evals)
    assert v.status is VerdictStatus.EXCLUDED          # G2 substantive
    assert v.failed_gates == (GateCode.G2, GateCode.G7)  # GATE_ORDER, deduped
    # both month-specific G7 reasons retained (nothing dropped)
    assert sum("no payslip" in r for r in v.reasons) == 2


def test_borderline_g5_passing_still_qualifies():
    """ANS-007 shape: ambiguous designation passes G5 with needs_review -> QUALIFIES."""
    evals = _all_pass(**{GateCode.G5: _ev(GateCode.G5, True, source=_REF, needs_review=True)})
    assert compute_verdict("ANS-007", evals).status is VerdictStatus.QUALIFIES


# ---------------------------------------------------------------------------
# 4. Batch + determinism + boundary
# ---------------------------------------------------------------------------
def test_compute_verdicts_batch_preserves_order():
    items = [
        ("A", _all_pass(), None),
        ("B", _all_pass(**{GateCode.G1: _ev(GateCode.G1, False, source=_REF)}), None),
    ]
    vs = compute_verdicts(items)
    assert [v.employee_id for v in vs] == ["A", "B"]
    assert vs[0].status is VerdictStatus.QUALIFIES
    assert vs[1].status is VerdictStatus.EXCLUDED


def test_determinism_identical_inputs():
    evals = _all_pass(**{GateCode.G1: _ev(GateCode.G1, False, source=_REF)})
    assert compute_verdict("X", evals) == compute_verdict("X", evals)


def test_verdict_does_not_import_llm():
    """Hard boundary (CLAUDE.md): validate/ must never import edb_claim.llm."""
    import edb_claim.validate.verdict as mod

    tree = ast.parse(open(mod.__file__, encoding="utf-8").read())
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert not any(m.startswith("edb_claim.llm") for m in imported), imported


# ---------------------------------------------------------------------------
# 5. Integration: real gates validate the source_ref classification convention
# ---------------------------------------------------------------------------
def _emp(citizenship):
    return Employee(
        id="X", name="N", entity="ent", citizenship=citizenship,
        ecmf_validated=True, no_other_grant=True,
        designation="ML Engineer", hire_type=HireType.UPSKILLED,
    )


def test_real_gate_g1_foreigner_excludes():
    """A real G1 failure carries a source_ref -> classified as exclusion."""
    g1 = gate_g1_local(_emp(Citizenship.FOREIGNER), None)
    assert g1.passed is False
    v = compute_verdict("X", [g1])
    assert v.status is VerdictStatus.EXCLUDED


def test_real_missing_salary_blocks_not_excludes():
    """Real G4+G7 with no payslip: G4 unverifiable (source None) + G7 missing -> BLOCKED."""
    g4 = gate_g4_salary_floor(None)
    g7 = gate_g7_payslip_present(2026, 4, None)
    assert g4.passed is False and g4.source_ref is None
    assert g7.passed is False and g7.source_ref is None
    v = compute_verdict("X", [g4, g7])
    assert v.status is VerdictStatus.BLOCKED


def test_real_below_floor_excludes():
    sal = SalaryRecord(employee_id="X", year=2026, month=1, basic_salary=4800.0, source_ref=_REF)
    g4 = gate_g4_salary_floor(sal)
    assert g4.passed is False and g4.source_ref is not None
    assert compute_verdict("X", [g4]).status is VerdictStatus.EXCLUDED


# ---------------------------------------------------------------------------
# Plain-assert harness (pytest-free fallback)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"ok   {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    sys.exit(1 if failed else 0)
