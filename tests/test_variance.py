"""Tests for edb_claim.calc.variance — the A-vs-B reconciliation (T8, PRD §6).

T8 is the highest-risk task (PLAN.md §3 #1): the report must *surface* the
genuine Method A vs Method B disagreement and never resolve it. The headline
case is **New-Hire B>A** (ANS-005: A=0, B>0, no timesheet evidence — SSRS 4400
risk, PRD §6 #2). These tests pin:

  * signed dollar / percent deltas (Δ relative to Method A, the submission basis);
  * the New-Hire isolation flag (requires BOTH new_hire AND B>A);
  * division-by-zero handling when A=0;
  * the material-divergence threshold (strict ``>``);
  * aggregate totals + flag-id collection + non-final caveat propagation;
  * determinism and the calc/ ↛ llm/ import boundary.

Runs under pytest OR directly via the plain-assert harness at the bottom.
"""

import ast
import json
import os
import sys
from dataclasses import replace

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from edb_claim.config import settings
from edb_claim.calc.variance import compute_variance, compute_variance_row
from edb_claim.domain.models import MethodAResult, MethodBResult

_EXPECTATIONS = os.path.join(_REPO_ROOT, "sample_data", "expectations.json")


# ---------------------------------------------------------------------------
# Builders — variance only reads employee_id / claim_amount / new_hire.
# ---------------------------------------------------------------------------
def _a(emp_id, claim):
    return MethodAResult(
        employee_id=emp_id,
        qualifying_cost_total=claim / settings.support_rate if settings.support_rate else 0.0,
        support_rate=settings.support_rate,
        claim_amount=claim,
    )


def _b(emp_id, claim, *, new_hire=False):
    return MethodBResult(
        employee_id=emp_id,
        qualifying_cost_total=claim / settings.support_rate if settings.support_rate else 0.0,
        support_rate=settings.support_rate,
        claim_amount=claim,
        new_hire=new_hire,
    )


def _load_oracle():
    with open(_EXPECTATIONS, encoding="utf-8") as fh:
        data = json.load(fh)
    return {e["employee_id"]: e for e in data["employees"]}


# ---------------------------------------------------------------------------
# 1. New-Hire B>A — the SSRS 4400 audit-risk row (PRD §6 #2)
# ---------------------------------------------------------------------------
def test_new_hire_b_greater_than_a_is_flagged():
    """ANS-005: A=0 (no hours), B>0 (forced D3=100%) -> isolate the row.

    Values come from the oracle (rate-driven: B is 3900 at the confirmed 60%),
    so this stays correct if the support rate changes.
    """
    oracle = _load_oracle()["ANS-005"]
    amount_a = oracle["method_a"]["claim_amount"]   # 0.0
    amount_b = oracle["method_b"]["claim_amount"]   # 3900.0 at 60%
    assert amount_a == 0.0 and amount_b > 0.0       # guard the fixture

    row = compute_variance_row(_a("ANS-005", amount_a), _b("ANS-005", amount_b, new_hire=True))
    assert row.new_hire_flag is True
    assert row.amount_a == 0.0 and row.amount_b == amount_b
    assert row.delta_abs == -amount_b               # signed: B claims more
    assert row.delta_pct is None                    # A=0 -> div-by-zero guarded
    assert row.material is False                    # no pct -> not "material"


def test_new_hire_flag_requires_b_to_exceed_a():
    """A New Hire whose A>=B is NOT flagged — the flag means B>A specifically."""
    row = compute_variance_row(_a("X", 5000.0), _b("X", 3000.0, new_hire=True))
    assert row.new_hire_flag is False


def test_non_new_hire_b_greater_than_a_is_not_new_hire_flagged():
    """B>A on a non-New-Hire row is a divergence, but NOT the New-Hire flag."""
    row = compute_variance_row(_a("X", 1000.0), _b("X", 4000.0, new_hire=False))
    assert row.new_hire_flag is False
    assert row.delta_abs == -3000.0


# ---------------------------------------------------------------------------
# 2. Signed deltas + percentage relative to Method A
# ---------------------------------------------------------------------------
def test_signed_dollar_and_percent_delta_relative_to_a():
    """ANS-001: A=17100, B=1408.62 -> A>B, Δ% relative to A."""
    oracle = _load_oracle()["ANS-001"]
    amount_a = oracle["method_a"]["claim_amount"]
    amount_b = oracle["method_b"]["claim_amount"]
    row = compute_variance_row(_a("ANS-001", amount_a), _b("ANS-001", amount_b))
    assert row.delta_abs == round(amount_a - amount_b, 2)
    assert row.delta_abs > 0                                   # A claims more
    assert row.delta_pct == round((amount_a - amount_b) / amount_a * 100.0, 2)
    assert row.material is True                                # huge gap


def test_negative_delta_when_b_exceeds_a():
    row = compute_variance_row(_a("X", 100.0), _b("X", 175.0))
    assert row.delta_abs == -75.0
    assert row.delta_pct == -75.0                             # (100-175)/100*100


# ---------------------------------------------------------------------------
# 3. Material threshold (strict >) + identical methods
# ---------------------------------------------------------------------------
def test_material_threshold_is_strict_greater_than():
    cfg = replace(settings, variance_material_pct=1.0)
    # exactly 1.0% -> NOT material (strict >)
    at = compute_variance_row(_a("X", 100.0), _b("X", 99.0), config=cfg)
    assert at.delta_pct == 1.0 and at.material is False
    # just over 1.0% -> material
    over = compute_variance_row(_a("X", 100.0), _b("X", 98.0), config=cfg)
    assert over.delta_pct == 2.0 and over.material is True


def test_identical_methods_zero_delta_not_material():
    row = compute_variance_row(_a("X", 1234.56), _b("X", 1234.56))
    assert row.delta_abs == 0.0
    assert row.delta_pct == 0.0
    assert row.material is False
    assert row.new_hire_flag is False


# ---------------------------------------------------------------------------
# 4. Guards
# ---------------------------------------------------------------------------
def test_mismatched_employee_ids_raise():
    try:
        compute_variance_row(_a("X", 1.0), _b("Y", 1.0))
    except ValueError:
        return
    raise AssertionError("expected ValueError on employee_id mismatch")


# ---------------------------------------------------------------------------
# 5. Aggregate report
# ---------------------------------------------------------------------------
def test_aggregate_totals_and_flag_collection():
    oracle = _load_oracle()
    pairs = []
    for eid in ("ANS-001", "ANS-002", "ANS-003", "ANS-004", "ANS-005"):
        e = oracle[eid]
        pairs.append((
            _a(eid, e["method_a"]["claim_amount"]),
            _b(eid, e["method_b"]["claim_amount"], new_hire=e["method_b"]["new_hire"]),
        ))
    rep = compute_variance(pairs)

    assert len(rep.rows) == 5
    assert rep.total_a == round(sum(r.amount_a for r in rep.rows), 2)
    assert rep.total_b == round(sum(r.amount_b for r in rep.rows), 2)
    assert rep.total_delta_abs == round(rep.total_a - rep.total_b, 2)
    assert rep.total_delta_pct == round((rep.total_a - rep.total_b) / rep.total_a * 100.0, 2)
    # Only ANS-005 is the New-Hire B>A audit-risk row.
    assert rep.new_hire_flagged == ("ANS-005",)
    # Every populated oracle row diverges materially from its counterpart.
    assert set(rep.materially_divergent) >= {"ANS-001", "ANS-002", "ANS-003", "ANS-004"}


def test_empty_report_has_zero_totals_and_none_pct():
    rep = compute_variance([])
    assert rep.rows == ()
    assert rep.total_a == 0.0 and rep.total_b == 0.0
    assert rep.total_delta_abs == 0.0
    assert rep.total_delta_pct is None
    assert rep.new_hire_flagged == ()


def test_support_rate_non_final_caveat_propagates():
    rep = compute_variance([(_a("X", 1.0), _b("X", 1.0))])
    assert rep.support_rate_is_final == settings.support_rate_is_final


# ---------------------------------------------------------------------------
# 6. Determinism & import boundary
# ---------------------------------------------------------------------------
def test_determinism_identical_inputs():
    pairs = [(_a("X", 17100.0), _b("X", 1408.62))]
    assert compute_variance(pairs) == compute_variance(pairs)


def test_variance_does_not_import_llm():
    """Hard boundary (CLAUDE.md): calc/ must never import edb_claim.llm."""
    import edb_claim.calc.variance as v

    tree = ast.parse(open(v.__file__, encoding="utf-8").read())
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert not any(m.startswith("edb_claim.llm") for m in imported), imported


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
