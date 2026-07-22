"""Per-trainee verdict engine — QUALIFIES / EXCLUDED / BLOCKED (PRD FR-6; T9).

Folds the per-person-month gate evaluations (T5, ``validate.gates``) and the
document-completeness rollup (T4, ``validate.completeness``) into **one verdict
per trainee** (FR-6). Every failed gate is carried onto the verdict with its
grounded reason and never silently dropped (FR-3/FR-6, CLAUDE.md).

Outcome precedence — **EXCLUDED > BLOCKED > QUALIFIES**:

  * **EXCLUDED** — a *substantive* eligibility gate failed: foreigner (G1),
    not ECMF-validated (G2), another government grant (G3), basic salary below
    the S$5,000 floor (G4), a non-qualifying designation (G5), or no involvement
    overlap with the claim window (G6). A definitively ineligible trainee is
    EXCLUDED even if documents are *also* missing — there is no point chasing
    evidence for someone who cannot qualify.
  * **BLOCKED** — the trainee is *otherwise* potentially eligible but a decision
    cannot be made because evidence is missing: a missing payslip (G7), a G4/G6
    that is *unverifiable* because its source value is absent (``source_ref is
    None``), or any BLOCKER cell in the completeness rollup (FR-2). Re-upload and
    re-run.
  * **QUALIFIES** — all gates pass and no blockers. Warnings (hours over
    capacity) and borderline-but-passing G5 designations
    (``needs_review``, refined later by T17) do **not** block.

Determinism (PRD §9): pure functions over already-ingested domain objects; no
I/O, no clock/random, **no LLM import** — ``validate/`` must run with the model
offline (CLAUDE.md). The LLM never decides a verdict.
"""

from __future__ import annotations

from typing import Iterable, Optional, Tuple

from edb_claim.domain.models import GateCode, Verdict, VerdictStatus
from edb_claim.validate.completeness import EmployeeRollup
from edb_claim.validate.gates import GATE_ORDER, GateEvaluation

# Gates whose failure means "cannot decide" (missing evidence) rather than
# "definitively ineligible". G7 (payslip presence) is always a blocker; G4/G6
# are blockers only when their source value is absent (``source_ref is None`` —
# e.g. no payslip to check the floor against), substantive exclusions otherwise.
_ALWAYS_BLOCKER_GATES: frozenset = frozenset({GateCode.G7})
_CONDITIONAL_BLOCKER_GATES: frozenset = frozenset({GateCode.G4, GateCode.G6})

_GATE_INDEX = {g: i for i, g in enumerate(GATE_ORDER)}


def _failure_is_blocker(ev: GateEvaluation) -> bool:
    """True if this *failed* gate is a missing-evidence blocker (vs an exclusion).

    G7 is always a blocker (it *is* the payslip-presence check). G4/G6 are
    blockers only when unverifiable — the gate reports failure with no
    ``source_ref`` because the value it needed (salary / involvement dates) was
    absent; with a source present, a G4/G6 failure is a substantive exclusion
    (below floor / no overlap). All other gates are exclusions.
    """
    gate = ev.gate
    if gate in _ALWAYS_BLOCKER_GATES:
        return True
    if gate in _CONDITIONAL_BLOCKER_GATES and ev.source_ref is None:
        return True
    return False


def compute_verdict(
    employee_id: str,
    evaluations: Iterable[GateEvaluation],
    *,
    rollup: Optional[EmployeeRollup] = None,
) -> Verdict:
    """Decide one trainee's verdict from all their gate evaluations (FR-6).

    Args:
        employee_id: the trainee.
        evaluations: every :class:`GateEvaluation` for this trainee across all
            their person-months (G1-G7 per month). Passing gates are ignored;
            failures are classified into exclusions vs blockers.
        rollup: optional completeness rollup (T4). When present, any BLOCKER cell
            (``blocker_count > 0``) contributes a BLOCKED signal — this catches
            entity-level blockers (missing workbook / RSE list / template) and
            missing payslips even if a per-month G7 evaluation was not supplied.

    Returns:
        A :class:`Verdict` whose ``failed_gates`` lists every distinct failed
        gate (in :data:`GATE_ORDER`) and whose ``reasons`` carry the grounded,
        de-duplicated explanations (FR-3) — nothing is dropped.
    """
    failed = [ev for ev in evaluations if not ev.passed]

    has_exclusion = any(not _failure_is_blocker(ev) for ev in failed)
    has_gate_blocker = any(_failure_is_blocker(ev) for ev in failed)
    has_doc_blocker = bool(rollup) and rollup.blocker_count > 0

    if has_exclusion:
        status = VerdictStatus.EXCLUDED
    elif has_gate_blocker or has_doc_blocker:
        status = VerdictStatus.BLOCKED
    else:
        status = VerdictStatus.QUALIFIES

    # Distinct failed gates, ordered by GATE_ORDER (stable for determinism/FR-7).
    failed_codes = sorted(
        {ev.gate for ev in failed}, key=lambda g: _GATE_INDEX.get(g, len(GATE_ORDER))
    )

    # Grounded reasons in encounter order, de-duplicated; fold in the rollup's
    # plain-language blocker summary when documents (not gates) drove a BLOCK.
    reasons: list = []
    seen: set = set()
    for ev in failed:
        if ev.reason and ev.reason not in seen:
            seen.add(ev.reason)
            reasons.append(ev.reason)
    if status is VerdictStatus.BLOCKED and has_doc_blocker and not has_gate_blocker:
        if rollup.summary and rollup.summary not in seen:
            reasons.append(rollup.summary)

    return Verdict(
        employee_id=employee_id,
        status=status,
        failed_gates=tuple(failed_codes),
        reasons=tuple(reasons),
    )


def compute_verdicts(
    items: Iterable[Tuple[str, Iterable[GateEvaluation], Optional[EmployeeRollup]]],
) -> Tuple[Verdict, ...]:
    """Batch helper: one verdict per ``(employee_id, evaluations, rollup)`` tuple.

    Input order is preserved (determinism). ``rollup`` may be ``None``.
    """
    return tuple(
        compute_verdict(emp_id, evals, rollup=rollup) for emp_id, evals, rollup in items
    )
