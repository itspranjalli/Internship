"""Grant-ceiling, disbursement and compliance-obligation helpers (EDB Support Package).

Pure, deterministic, side-effect-free (CLAUDE.md): given the config (and a claim
total) these return plain dicts the API/UI render. No arithmetic that touches a
claim *amount* lives here beyond the grant-ceiling/disbursement framing — the
per-person claim is still owned entirely by ``calc/`` (the LLM/UI never compute a
figure). See [[edb-scheme-rules-authoritative]] in memory for the source rules.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List

from edb_claim.config import Config


def _add_months(d: date, months: int) -> date:
    """Add calendar months to a date, clamping the day to the month length."""
    m = d.month - 1 + months
    year = d.year + m // 12
    month = m % 12 + 1
    # clamp day (e.g. 31 Jan + 1 month -> 28/29 Feb)
    import calendar as _cal

    day = min(d.day, _cal.monthrange(year, month)[1])
    return date(year, month, day)


def grant_summary(total_claim: float, config: Config) -> Dict[str, Any]:
    """Where this submission sits against the S$42m manpower ceiling + 70/30 gate.

    The 70% disbursement gate is on **cumulative disbursements vs the Maximum
    Grant Amount** (not on a single claim): up to 70% of S$42m (= S$29.4m) may be
    disbursed before project completion; the final 30% (S$12.6m) is released only
    on completion + fulfilment of all T&Cs. For a single POC claim this is
    informational (well under the cap).
    """
    max_grant = float(config.max_grant_amount)
    threshold = config.disbursement_threshold_pct
    pre_completion_cap = round(max_grant * threshold, 2)
    return {
        "max_grant_amount": max_grant,
        "manpower_only": True,
        "total_claim": round(total_claim, 2),
        "pct_of_grant": (round(total_claim / max_grant, 6) if max_grant else 0.0),
        "within_grant": total_claim <= max_grant,
        "disbursement_threshold_pct": threshold,
        "pre_completion_cap": pre_completion_cap,          # 70% of max grant
        "post_completion_holdback": round(max_grant - pre_completion_cap, 2),  # 30%
        "this_claim_fully_disbursable": total_claim <= pre_completion_cap,
    }


def claim_period_months(config: Config) -> int:
    """Inclusive calendar-month span of the claim window (for the ≥3-month rule)."""
    s, e = config.claim_period_start, config.claim_period_end
    return (e.year - s.year) * 12 + (e.month - s.month) + 1


def obligations(config: Config) -> List[Dict[str, Any]]:
    """The audit / reporting / process obligations, with concrete dates where known.

    Dates are derived deterministically from the config windows; cadence-only
    items (e.g. "as notified by EDB") carry no fixed date. ``status`` is a light
    self-check the UI can colour (ok / attention / info).
    """
    qp_start, qp_end = config.qualifying_period_start, config.qualifying_period_end
    first_claim_start = config.claim_period_start
    months = claim_period_months(config)
    out: List[Dict[str, Any]] = [
        {
            "key": "min_claim_period",
            "title": "Each claim covers at least 3 months",
            "detail": f"This claim window spans {months} month(s) "
                      f"({first_claim_start:%d %b %Y} – {config.claim_period_end:%d %b %Y}).",
            "due": None,
            "status": "ok" if months >= config.min_claim_months else "attention",
        },
        {
            "key": "external_audit",
            "title": "External audit by an ACRA-registered Public Accountant (Practitioner)",
            "detail": "All claims must be audited under SSRS 4400 and the Practitioner's "
                      "Report sent directly from the Practitioner to EDB.",
            "due": None,
            "status": "info",
        },
        {
            "key": "practitioner_report_cadence",
            "title": "Practitioner's Report at least every 12 months",
            "detail": "From the start of the first claim period, with the stamped Claim Forms.",
            "due": _add_months(first_claim_start, config.audit_report_interval_months).isoformat(),
            "status": "info",
        },
        {
            "key": "final_audited_claim",
            "title": "Final Audited Claim within 183 days of the Qualifying Period end",
            "detail": f"Qualifying Period ends {qp_end:%d %b %Y}; full documentation due by the date shown.",
            "due": (qp_end + timedelta(days=config.final_submission_days)).isoformat(),
            "status": "info",
        },
        {
            "key": "annual_progress_update",
            "title": "Annual Progress Update to EDB",
            "detail": "Submitted as and when notified by EDB.",
            "due": None,
            "status": "info",
        },
        {
            "key": "final_progress_update",
            "title": "Final Progress Update within 183 days of project completion",
            "detail": "Within 183 calendar days from completion or termination of the Project.",
            "due": None,
            "status": "info",
        },
        {
            "key": "ihq_annual_report",
            "title": "BA progress report to IHQ — annually, before any claims",
            "detail": "All Business Areas submit a progress report to IHQ each year before claim submission.",
            "due": None,
            "status": "info",
        },
        {
            "key": "inspection",
            "title": "Permit EDB inspection on ≥ 2 weeks' written notice",
            "detail": "EDB officers (or nominees) may inspect the premises where the Project is carried out.",
            "due": None,
            "status": "info",
        },
    ]
    return out
