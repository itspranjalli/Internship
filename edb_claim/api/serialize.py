"""Serialise the deterministic :class:`PipelineResult` to plain JSON for the UI.

Pure, read-only mapping from the frozen dataclasses in ``edb_claim.app.pipeline``
and ``edb_claim.domain.models`` to dicts. No arithmetic happens here — every
figure is copied verbatim from the audited engine so the API can never alter a
claim amount (CLAUDE.md hard boundary).
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from edb_claim.app.pipeline import EmployeeResult, EntityResult, PipelineResult
from edb_claim.compliance import claim_period_months, grant_summary, obligations
from edb_claim.config import settings
from edb_claim.domain.calendar_utils import weekdays_in_month
from edb_claim.domain.models import EvidenceRef

# Plain-language names for the eligibility gates (mirrors the HR-facing labels).
CHECK_NAMES: Dict[str, str] = {
    "G1": "Singapore Citizen or PR",
    "G2": "ECMF-validated researcher",
    "G3": "Not funded by another government grant",
    "G4": "Meets the minimum salary ($5,000/month)",
    "G5": "Eligible R&D role (not Marketing / HR / Sales / etc.)",
    "G6": "Active during the claim period",
    "G7": "Payslip provided for each month",
}
_GATE_ORDER = ["G1", "G2", "G3", "G4", "G5", "G6", "G7"]


def _date(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d else None


def _evref(ref: Optional[EvidenceRef]) -> Optional[Dict[str, Any]]:
    if ref is None:
        return None
    return {
        "file": ref.file,
        "sheet": ref.sheet,
        "cell": ref.cell_or_row,
        "label": ref.label,
    }


def _cell(c) -> Dict[str, Any]:
    return {
        "employee_id": c.employee_id,
        "entity": c.entity,
        "doc_type": c.doc_type.value,
        "doc_label": c.doc_type.value.replace("_", " "),
        "scope": c.scope.value,
        "status": c.status.value,
        "severity": c.severity.value,
        "month": c.month,
        "reason": c.reason,
        "source": _evref(c.source_ref),
    }


def _gate_summary(e: EmployeeResult) -> List[Dict[str, Any]]:
    """Collapse the per-person-month gate evaluations into one row per gate."""
    out: List[Dict[str, Any]] = []
    for code in _GATE_ORDER:
        evs = [ev for ev in e.gate_evaluations if ev.gate.value == code]
        if not evs:
            continue
        passed = all(ev.passed for ev in evs)
        fail = next((ev for ev in evs if not ev.passed), None)
        out.append({
            "code": code,
            "name": CHECK_NAMES.get(code, code),
            "passed": passed,
            "reason": (fail.reason if fail and fail.reason else "") if not passed else "",
            "needs_review": any(ev.needs_review for ev in evs),
        })
    return out


def _month_detail(m, *, salary_src: Optional[Dict[str, Any]], hours_src: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """One Method-A month, reconstructed for HR with its inputs + source docs.

    The breakdown stores capped_salary / month_fraction / time_contribution; we
    rebuild the human-readable inputs from them: weekday capacity for the month,
    the implied project hours (exact when time<100%, ≥capacity when clamped), and
    the worked-vs-total weekdays behind a partial-month fraction. Every figure is
    tagged with the document it came from (payslip / Time Sheet) so the claim is
    never a black box (PRD FR-7/FR-14).
    """
    weekdays = weekdays_in_month(m.year, m.month)
    capacity = round(weekdays * settings.hours_per_day, 2)
    clamped = m.time_contribution >= 1.0 - 1e-9
    implied_hours = None if clamped else round(m.time_contribution * capacity, 1)
    full_month = m.month_fraction >= 1.0 - 1e-9
    worked_weekdays = weekdays if full_month else round(m.month_fraction * weekdays)
    return {
        "year": m.year,
        "month": m.month,
        "capped_salary": m.capped_salary,
        "salary_capped": abs(m.capped_salary - settings.salary_cap) < 1e-6,
        "month_fraction": m.month_fraction,
        "full_month": full_month,
        "weekdays": weekdays,
        "worked_weekdays": worked_weekdays,
        "time_contribution": m.time_contribution,
        "time_clamped": clamped,
        "capacity_hours": capacity,
        "implied_hours": implied_hours,
        "qualifying_cost": m.qualifying_cost,
        "salary_source": salary_src,
        "hours_source": hours_src,
    }


def _employee(
    e: EmployeeResult,
    *,
    payslip_src: Dict[Tuple[str, int], Dict[str, Any]],
    hours_src: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    emp = e.employee
    return {
        "id": emp.id,
        "name": emp.name,
        "entity": emp.entity,
        "designation": emp.designation,
        "status": e.verdict.status.value,
        "qualifies": e.qualifies,
        "needs_review": e.needs_review,
        "zero_claim": e.zero_claim,
        "reasons": list(e.verdict.reasons),
        "monthly_basic_salary": e.monthly_basic_salary,
        "claim_amount": e.method_a.claim_amount,
        "qualifying_cost_total": e.method_a.qualifying_cost_total,
        "support_rate": e.method_a.support_rate,
        "months_capped": e.method_a.months_capped,
        "crosscheck_ok": e.crosscheck_ok,
        "involvement_from": _date(e.involvement_from),
        "involvement_to": _date(e.involvement_to),
        "method_b": (
            {"claim_amount": e.method_b.claim_amount, "new_hire": e.method_b.new_hire}
            if e.method_b is not None else None
        ),
        "gates": _gate_summary(e),
        "monthly": [
            _month_detail(
                m,
                salary_src=payslip_src.get((emp.id, m.month)),
                hours_src=hours_src,
            )
            for m in e.method_a.monthly
        ],
    }


def _variance(v) -> Dict[str, Any]:
    return {
        "total_a": v.total_a,
        "total_b": v.total_b,
        "total_delta_abs": v.total_delta_abs,
        "rows": [
            {
                "employee_id": r.employee_id,
                "amount_a": r.amount_a,
                "amount_b": r.amount_b,
                "delta_abs": r.delta_abs,
                "material": r.material,
                "new_hire_flag": r.new_hire_flag,
            }
            for r in v.rows
        ],
    }


def _entity(ent: EntityResult) -> Dict[str, Any]:
    rb = ent.completeness.rollup
    # (employee_id, month) -> payslip source ref, from the present PAYSLIP cells,
    # so each month's salary input links back to the exact payslip evidence.
    payslip_src: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for c in ent.completeness.cells:
        if (c.doc_type.value == "payslip" and c.status.value == "present"
                and c.employee_id and c.month and c.source_ref):
            payslip_src[(c.employee_id, c.month)] = _evref(c.source_ref)
    # the Time Sheet is the source of project hours; link to the workbook itself.
    hours_src = (
        {"file": os.path.basename(ent.file), "sheet": "Time Sheet", "cell": None,
         "label": "Time Sheet (project hours)"}
        if ent.file else None
    )
    return {
        "entity": ent.entity,
        "file": ent.file,
        "rollup": {
            "employee_count": rb.employee_count,
            "ready_count": rb.ready_count,
            "blocked_count": rb.blocked_count,
            "blocker_count": rb.blocker_count,
            "warning_count": rb.warning_count,
            "summary": rb.summary,
        },
        "blockers": [_cell(c) for c in ent.completeness.blocker_cells],
        "warnings": [_cell(c) for c in ent.completeness.warning_cells],
        # full matrix (present + missing + inconsistent) so the UI can render a
        # document tracker that ticks what's present and lists what's missing.
        "cells": [_cell(c) for c in ent.completeness.cells],
        "employees": [
            _employee(e, payslip_src=payslip_src, hours_src=hours_src)
            for e in ent.employees
        ],
        "variance": _variance(ent.variance),
        "ingest_warnings": list(ent.ingest_warnings),
    }


def result_to_dict(res: PipelineResult) -> Dict[str, Any]:
    """Full JSON-able view of one pipeline run (what the React app renders)."""
    emps = res.all_employees
    return {
        "support_rate": res.support_rate,
        "support_rate_is_final": res.support_rate_is_final,
        "claim_period": [_date(res.claim_period[0]), _date(res.claim_period[1])],
        "total_claim_a": res.total_claim_a,
        "total_claim_b": res.total_claim_b,
        "grant": grant_summary(res.total_claim_a, settings),
        "compliance": obligations(settings),
        "claim_months": claim_period_months(settings),
        "min_claim_months": settings.min_claim_months,
        "errors": list(res.errors),
        "counts": {
            "total": len(emps),
            "qualify": sum(1 for e in emps if e.qualifies),
            "blocked": sum(1 for e in emps if e.verdict.status.value == "BLOCKED"),
            "excluded": sum(1 for e in emps if e.verdict.status.value == "EXCLUDED"),
            "needs_review": sum(1 for e in emps if e.needs_review),
        },
        "entities": [_entity(ent) for ent in res.entities],
    }
