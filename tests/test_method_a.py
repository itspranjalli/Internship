"""Tests for edb_claim.calc.method_a — the Method A (EDB pro-ration) engine.

The two non-negotiable cent oracles (PLAN.md §3 risk #2, PRD §11.3):

  1. EDB's own worked example (``Salary Pro-ration E.g.`` sheet):
     9,500 over 15 Jan – 31 Mar 2018 at 30%  ->  **$7,310.87**.
  2. The T14 synthetic oracle (``sample_data/expectations.json``): every Method A
     ``claim_amount`` for ANS-001..005, including the partial-month joiner
     (8,727.27) and the New-Hire-no-hours case (0.00).

Also asserts the import boundary: calc/ must NEVER import edb_claim.llm.

Runs under pytest (`.venv/bin/python -m pytest tests/test_method_a.py -q`) OR
directly (`python tests/test_method_a.py`) via the plain-assert harness below.
"""

import json
import os
import sys
from dataclasses import replace
from datetime import date

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from edb_claim.config import settings
from edb_claim.calc.method_a import ClaimableMonth, compute_method_a
from edb_claim.domain.models import HireType

_EXPECTATIONS = os.path.join(_REPO_ROOT, "sample_data", "expectations.json")


def _load_expectations():
    with open(_EXPECTATIONS, encoding="utf-8") as fh:
        return json.load(fh)


# Default involvement windows per employee from the §8 case definitions, used to
# clip the joiner/leaver months. Months outside the window simply aren't fed.
_WINDOWS = {
    "ANS-002": (date(2026, 3, 12), date(2026, 6, 30)),  # joiner
    "ANS-003": (date(2026, 1, 1), date(2026, 5, 15)),   # leaver
}


def _claimables_from_oracle(emp):
    """Build ClaimableMonth inputs from an oracle employee's monthly rows.

    Salary and hours come straight from the oracle; the involvement window
    (joiner/leaver) drives month_fraction. We deliberately do NOT feed the
    oracle's month_fraction — the engine must derive it from calendar_utils and
    still hit the cent.
    """
    p_start, p_end = _WINDOWS.get(emp["employee_id"], (None, None))
    out = []
    for row in emp["method_a"]["monthly"]:
        out.append(
            ClaimableMonth(
                year=2026,
                month=row["month"],
                basic_salary=float(row["capped_salary"]),  # pre-cap value happens to be capped already in oracle
                hours=float(row["hours"]),
                period_start=p_start,
                period_end=p_end,
            )
        )
    return out


# ---------------------------------------------------------------------------
# 1. EDB worked example — the headline cent oracle: 7,310.87
# ---------------------------------------------------------------------------
def test_edb_worked_example_7310_87():
    """9,500 over 15 Jan-31 Mar 2018, 100% time, 30% support -> $7,310.87.

    Jan is the partial month (13/23 weekdays); Feb & Mar are whole. Hours are
    set to full weekday capacity so time_contribution == 1.0 (the example
    assumes 100% time). Round only the final claim.
    """
    hpd = settings.hours_per_day
    # weekday capacity per month so time_contribution clamps to exactly 1.0
    months = [
        ClaimableMonth(2018, 1, 9500.0, 23 * hpd, date(2018, 1, 15), date(2018, 3, 31)),
        ClaimableMonth(2018, 2, 9500.0, 20 * hpd, date(2018, 1, 15), date(2018, 3, 31)),
        ClaimableMonth(2018, 3, 9500.0, 22 * hpd, date(2018, 1, 15), date(2018, 3, 31)),
    ]
    # EDB's published example is at their stated 30% support; pin it explicitly so
    # this method check stays independent of our scheme's confirmed 60% rate.
    res = compute_method_a("EDB-EXAMPLE", months, config=replace(settings, support_rate=0.30))

    # Jan fraction must be 13/23 exactly (the oracle's partial month).
    jan = res.monthly[0]
    assert jan.month_fraction == 13 / 23, jan.month_fraction
    assert jan.time_contribution == 1.0
    # Feb/Mar whole months -> fraction 1.0.
    assert res.monthly[1].month_fraction == 1.0
    assert res.monthly[2].month_fraction == 1.0
    # The cent oracle.
    assert res.claim_amount == 7310.87, res.claim_amount


def test_edb_example_qualifying_cost_not_prerounded():
    """Qualifying-cost total stays full precision (24,369.56... not 24,369.56)."""
    hpd = settings.hours_per_day
    months = [
        ClaimableMonth(2018, 1, 9500.0, 23 * hpd, date(2018, 1, 15), date(2018, 3, 31)),
        ClaimableMonth(2018, 2, 9500.0, 20 * hpd, date(2018, 1, 15), date(2018, 3, 31)),
        ClaimableMonth(2018, 3, 9500.0, 22 * hpd, date(2018, 1, 15), date(2018, 3, 31)),
    ]
    res = compute_method_a("EDB-EXAMPLE", months)
    # 9500*13/23 + 9500 + 9500 = 24369.565217...; NOT rounded to 24369.56.
    expected = 9500.0 * (13 / 23) + 9500.0 + 9500.0
    assert res.qualifying_cost_total == expected
    assert res.qualifying_cost_total != round(expected, 2)


# ---------------------------------------------------------------------------
# 2. T14 oracle — every Method A claim_amount to the cent
# ---------------------------------------------------------------------------
# At the confirmed 60% support rate (EDB Support Package). Note ANS-002 lands at
# 17454.55 — round(qct×0.60) is a cent above 2×round(qct×0.30), so these are the
# regenerated oracle values, not a doubling of the old 30% figures.
_ORACLE_CLAIMS = {
    "ANS-001": 34200.00,
    "ANS-002": 17454.55,  # mid-period joiner, Mar 14/22
    "ANS-003": 19000.00,  # mid-period leaver, May 11/21
    "ANS-004": 72000.00,  # salary 23,000 capped to 20,000
    "ANS-005": 0.00,      # New Hire, zero hours -> Method A = 0
}


def test_t14_oracle_claims_to_the_cent():
    data = _load_expectations()
    by_id = {e["employee_id"]: e for e in data["employees"]}
    for emp_id, expected_claim in _ORACLE_CLAIMS.items():
        emp = by_id[emp_id]
        months = _claimables_from_oracle(emp)
        res = compute_method_a(emp_id, months)
        assert res.claim_amount == expected_claim, (
            emp_id,
            res.claim_amount,
            expected_claim,
        )
        # qualifying_cost_total also matches the oracle's full-precision figure.
        assert abs(
            res.qualifying_cost_total - emp["method_a"]["qualifying_cost_total"]
        ) < 1e-6, (emp_id, res.qualifying_cost_total)


def test_t14_oracle_per_month_breakdown_retained():
    """FR-4: every month is retained with matching fraction/time/cost."""
    data = _load_expectations()
    by_id = {e["employee_id"]: e for e in data["employees"]}
    for emp_id in _ORACLE_CLAIMS:
        emp = by_id[emp_id]
        months = _claimables_from_oracle(emp)
        res = compute_method_a(emp_id, months)
        oracle_rows = emp["method_a"]["monthly"]
        assert len(res.monthly) == len(oracle_rows), emp_id
        for got, want in zip(res.monthly, oracle_rows):
            assert got.month == want["month"]
            assert abs(got.month_fraction - want["month_fraction"]) < 1e-6, (
                emp_id, got.month, got.month_fraction, want["month_fraction"],
            )
            assert abs(got.time_contribution - want["time_contribution"]) < 1e-6
            assert abs(got.qualifying_cost - want["qualifying_cost"]) < 1e-6, (
                emp_id, got.month, got.qualifying_cost, want["qualifying_cost"],
            )


def test_joiner_partial_month_fraction_14_over_22():
    """ANS-002: March is clipped to 12-31 Mar -> 14/22, full precision cost."""
    data = _load_expectations()
    by_id = {e["employee_id"]: e for e in data["employees"]}
    res = compute_method_a("ANS-002", _claimables_from_oracle(by_id["ANS-002"]))
    march = res.monthly[0]
    assert march.month == 3
    assert march.month_fraction == 14 / 22, march.month_fraction
    assert march.capped_salary == 8000.0
    # Full-time hours are recorded at 2dp (193.6), while capacity is full
    # precision (22*8.8 = 193.60000000000002), so the ratio lands a float-ULP
    # under 1.0. That is the correct full-precision value (the engine rounds
    # only the final claim, per CLAUDE.md); assert ~1.0 within float tolerance.
    assert abs(march.time_contribution - 1.0) < 1e-9, march.time_contribution
    # 8000 * 14/22 = 5090.909090..., NOT pre-rounded.
    assert abs(march.qualifying_cost - 8000.0 * 14 / 22) < 1e-9
    assert res.claim_amount == 17454.55


def test_new_hire_zero_hours_is_zero():
    """ANS-005: New Hire, zero hours -> time_contribution 0 -> claim 0.00."""
    data = _load_expectations()
    by_id = {e["employee_id"]: e for e in data["employees"]}
    res = compute_method_a("ANS-005", _claimables_from_oracle(by_id["ANS-005"]))
    assert all(m.time_contribution == 0.0 for m in res.monthly)
    assert res.qualifying_cost_total == 0.0
    assert res.claim_amount == 0.0


def test_salary_cap_clamp_not_a_gate():
    """ANS-004: basic 23,000 -> capped 20,000 per month (arithmetic clamp)."""
    months = [
        ClaimableMonth(2026, m, 23000.0, wd * settings.hours_per_day)
        for m, wd in [(1, 22), (2, 20), (3, 22), (4, 22), (5, 21), (6, 22)]
    ]
    res = compute_method_a("ANS-004", months)
    assert all(b.capped_salary == 20000.0 for b in res.monthly)
    assert res.claim_amount == 72000.00


# ---------------------------------------------------------------------------
# 2b. EDB Support Package — existing-staff (upskill to PL3) 9-month cap
# ---------------------------------------------------------------------------
def _twelve_full_months() -> list:
    """12 consecutive full, full-time months at 10,000 basic (Jan 2026 – Dec 2026)."""
    hpd = settings.hours_per_day
    out = []
    for k in range(12):
        out.append(ClaimableMonth(2026, k + 1, 10000.0, 31 * hpd))  # > capacity -> time=1.0
    return out


def test_upskill_cap_limits_existing_staff_to_nine_months():
    """Upskilled/Reskilled staff are funded for at most config.upskill_max_months (9)."""
    months = _twelve_full_months()
    up = compute_method_a("UP-1", months, hire_type=HireType.UPSKILLED)
    re_ = compute_method_a("RE-1", months, hire_type=HireType.RESKILLED)
    assert len(up.monthly) == settings.upskill_max_months == 9
    assert up.months_capped == 12 - 9 == 3
    assert len(re_.monthly) == 9 and re_.months_capped == 3
    # kept months are the EARLIEST 9 (anchor "first_qualifying")
    assert [m.month for m in up.monthly] == list(range(1, 10))
    # 9 full months × 10,000 × 60% = 54,000
    assert up.claim_amount == 54000.00


def test_new_hire_not_capped():
    """New hires are funded across the qualifying period — no 9-month cap."""
    months = _twelve_full_months()
    nh = compute_method_a("NH-1", months, hire_type=HireType.NEW_HIRE)
    assert len(nh.monthly) == 12 and nh.months_capped == 0
    # 12 full months × 10,000 × 60% = 72,000  (> the capped upskill claim)
    assert nh.claim_amount == 72000.00


# ---------------------------------------------------------------------------
# 3. Determinism & import boundary
# ---------------------------------------------------------------------------
def test_determinism_identical_inputs():
    months = [ClaimableMonth(2026, 1, 9500.0, 22 * settings.hours_per_day)]
    a = compute_method_a("X", months)
    b = compute_method_a("X", months)
    assert a == b


def test_calc_does_not_import_llm():
    """Hard boundary (CLAUDE.md): calc/ must never import edb_claim.llm.

    Checked via AST so the assertion targets real ``import`` statements, not the
    docstring that legitimately *documents* the boundary by naming the module.
    """
    import ast

    import edb_claim.calc.method_a as ma

    tree = ast.parse(open(ma.__file__, encoding="utf-8").read())
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert not any(m.startswith("edb_claim.llm") for m in imported), imported
    # No llm module loaded as a (transitive) side effect of importing the engine.
    # Checked in a clean subprocess: in a full-suite run a sibling test
    # (test_llm_client) has already imported edb_claim.llm into this process's
    # sys.modules, so an in-process check would be meaningless.
    import subprocess

    probe = (
        "import sys; import edb_claim.calc.method_a; "
        "leaked=[n for n in sys.modules if n.startswith('edb_claim.llm')]; "
        "sys.exit('LLM leaked: %r' % leaked if leaked else 0)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe], cwd=_REPO_ROOT, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


# ---------------------------------------------------------------------------
# Plain-assert harness (pytest-free fallback)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
