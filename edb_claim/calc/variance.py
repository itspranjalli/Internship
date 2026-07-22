"""Method A vs Method B variance / reconciliation report (PRD §6, FR-4).

This is the **highest-risk** task (PLAN.md §3 #1). The two engines genuinely
disagree and a ruling from EDB/the auditor is *pending* (PRD §10 Q1; CLAUDE.md).
This module's job is to **surface** the gap per trainee and in aggregate — it
must **never resolve it**, "fix" Method B's quirks, or pick a winner:

  * Method A (``calc.method_a``) — EDB monthly pro-ration, the *presumptive
    submission basis* (the figure on the EDB output template).
  * Method B (``calc.method_b``) — internal Staff Costs replica, quirks intact
    (New-Hire auto-100% time; ``[B]`` labelled "annual" but computed monthly).

The headline audit risk is the **New-Hire B>A** row: Method B forces
``[D3]=100%`` for a New Hire even with *no* recorded timesheet hours, so it
claims a positive amount where Method A — which has no hours to pro-rate —
claims zero. Such a claim has no timesheet evidence and is an SSRS 4400 sampling
risk (PRD §6 #2); it is isolated via ``new_hire_flag`` regardless of magnitude.

**Boundaries (CLAUDE.md):** pure functions, stdlib + domain/config only;
``calc/`` MUST NEVER import ``edb_claim.llm``. Deterministic: same inputs →
identical report. Both ``claim_amount``s are already cent-rounded by their
engines (``ROUND(·,2)``); the small derived deltas here round to 2dp ($) / 2dp
(%) for a stable, presentable reconciliation — no claim figure is recomputed.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence, Tuple

from edb_claim.config import Config, settings
from edb_claim.domain.models import (
    MethodAResult,
    MethodBResult,
    VarianceReport,
    VarianceRow,
)


# ---------------------------------------------------------------------------
# Per-employee row
# ---------------------------------------------------------------------------
def _delta_pct(amount_a: float, amount_b: float) -> Optional[float]:
    """Signed Δ% of A vs B relative to A (the submission basis).

    ``(amount_a - amount_b) / amount_a × 100``, rounded to 2dp. Returns ``None``
    when ``amount_a == 0`` (division by zero) — e.g. the New-Hire-no-hours case
    where A=0 but B>0; that row is caught by ``new_hire_flag`` instead.
    """
    if amount_a == 0:
        return None
    return round((amount_a - amount_b) / amount_a * 100.0, 2)


def compute_variance_row(
    a: MethodAResult,
    b: MethodBResult,
    *,
    config: Optional[Config] = None,
) -> VarianceRow:
    """Reconcile one trainee's Method A and Method B claim amounts (PRD §6).

    ``delta_abs`` is the dollar gap ``amount_a - amount_b`` (signed: positive =
    A claims more); ``delta_pct`` is the same relative to A (``None`` if A=0).
    ``new_hire_flag`` marks the audit-risk New-Hire B>A row (PRD §6 #2).
    ``material`` marks ``|delta_pct|`` over ``config.variance_material_pct``.

    Args:
        a: Method A result (same ``employee_id`` as ``b``).
        b: Method B result; ``b.new_hire`` drives the New-Hire isolation flag.
        config: tunables (``variance_material_pct``). Defaults to ``settings``.

    Returns:
        A :class:`VarianceRow`. Raises ``ValueError`` if the two results are for
        different employees (guards a mis-zip at the call site).
    """
    if a.employee_id != b.employee_id:
        raise ValueError(
            f"variance row mismatch: A={a.employee_id!r} vs B={b.employee_id!r}"
        )
    cfg = config if config is not None else settings

    amount_a = a.claim_amount
    amount_b = b.claim_amount
    delta_abs = round(amount_a - amount_b, 2)
    delta_pct = _delta_pct(amount_a, amount_b)

    # New-Hire B>A: positive Method B claim with no timesheet basis (PRD §6 #2).
    new_hire_flag = bool(b.new_hire) and amount_b > amount_a
    material = delta_pct is not None and abs(delta_pct) > cfg.variance_material_pct

    return VarianceRow(
        employee_id=a.employee_id,
        amount_a=amount_a,
        amount_b=amount_b,
        delta_abs=delta_abs,
        delta_pct=delta_pct,
        new_hire_flag=new_hire_flag,
        material=material,
    )


# ---------------------------------------------------------------------------
# Aggregate report
# ---------------------------------------------------------------------------
def compute_variance(
    pairs: Iterable[Tuple[MethodAResult, MethodBResult]],
    *,
    config: Optional[Config] = None,
) -> VarianceReport:
    """Build the aggregate A-vs-B reconciliation report (PRD §6, FR-4).

    Reconciles each ``(MethodAResult, MethodBResult)`` pair, then totals the two
    methods' rounded claim amounts. ``new_hire_flagged`` / ``materially_divergent``
    collect the employee ids tripping each flag (input order preserved). The
    report does not rank or resolve the methods (ruling pending, PRD §10 Q1).

    Args:
        pairs: ``(A, B)`` results, one pair per trainee. Each pair must share an
            ``employee_id`` (enforced by :func:`compute_variance_row`).
        config: tunables. Defaults to the canonical :data:`settings`.

    Returns:
        A :class:`VarianceReport` carrying every row, the totals, the flagged-id
        lists, and the ``support_rate_is_final`` non-final caveat.
    """
    cfg = config if config is not None else settings

    rows = tuple(compute_variance_row(a, b, config=cfg) for a, b in pairs)

    total_a = round(sum(r.amount_a for r in rows), 2)
    total_b = round(sum(r.amount_b for r in rows), 2)
    total_delta_abs = round(total_a - total_b, 2)
    total_delta_pct = (
        round((total_a - total_b) / total_a * 100.0, 2) if total_a != 0 else None
    )

    new_hire_flagged = tuple(r.employee_id for r in rows if r.new_hire_flag)
    materially_divergent = tuple(r.employee_id for r in rows if r.material)

    return VarianceReport(
        rows=rows,
        total_a=total_a,
        total_b=total_b,
        total_delta_abs=total_delta_abs,
        total_delta_pct=total_delta_pct,
        new_hire_flagged=new_hire_flagged,
        materially_divergent=materially_divergent,
        support_rate_is_final=cfg.support_rate_is_final,
    )
