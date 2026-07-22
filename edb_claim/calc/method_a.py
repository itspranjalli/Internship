"""Method A — EDB monthly pro-ration calculation engine (PRD §6, FR-4).

This is the **presumptive submission basis**: the figure that goes onto the EDB
output template's ``Manpower_Locals`` rows. It must reproduce, to the cent:

  * EDB's own worked example (``Salary Pro-ration E.g.`` sheet): 9,500 over
    15 Jan – 31 Mar 2018 at 30% support  ->  **$7,310.87**; and
  * the T14 synthetic oracle (``sample_data/expectations.json``).

Formula (PRD §6)::

    qualifying_cost   = Σ_m  capped_salary(m) × month_fraction(m) × time_contribution(m)
    capped_salary(m)  = min(basic_salary(m), config.salary_cap)
    month_fraction(m) = (involvement ∩ claim window) overlap / weekdays(m)   [1.0 if whole month]
    time_contribution(m) = min(1, hours(m) / (weekdays(m) × config.hours_per_day))
    claim_amount      = round(qualifying_cost × support_rate, 2)

**Rounding rule (the cent oracle):** carry FULL float precision throughout; round
*only* the final ``claim_amount``, mirroring the template's ``I = ROUND(G×H, 2)``.
The per-month ``qualifying_cost`` and the ``qualifying_cost_total`` are NEVER
pre-rounded (PRD §6; PLAN.md §3 risk #2).

**Layering (PRD §6 floor/cap):** the cap is an arithmetic CLAMP applied here
(``min(salary, cap)``). The S$5,000 floor is an *exclusion gate* (G4) owned by
T5/validate — it is NOT applied here. This engine consumes the claimable
person-months it is given and runs no eligibility gates (T5 owns eligibility).

**Determinism & boundaries (CLAUDE.md):** pure functions, stdlib + domain only.
``calc/`` MUST NEVER import ``edb_claim.llm`` — the LLM never computes claim
amounts. Calendar / weekday math is REUSED from ``domain.calendar_utils`` (not
reinvented).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional, Sequence

from edb_claim.config import Config, settings
from edb_claim.domain.calendar_utils import month_fraction as _month_fraction
from edb_claim.domain.calendar_utils import weekdays_in_month
from edb_claim.domain.models import HireType, MethodAResult, MonthlyBreakdownA


# ---------------------------------------------------------------------------
# Input unit
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ClaimableMonth:
    """One claimable employee-month fed to the Method A engine (PRD §6).

    This is the engine's *input contract*: a person-month that T5 has deemed
    claimable, enriched with the basic monthly salary (from T3 payroll) and the
    project hours (from the T2 Time Sheet). ``period_start`` / ``period_end`` are
    the employee's involvement window already intersected with the claim window
    (joiner/leaver clipping) — they drive ``month_fraction``. For a full,
    unclipped month they may be left as ``None`` and the whole month counts
    (fraction 1.0).

    The engine does NOT re-run gates; it caps the salary (arithmetic clamp) and
    pro-rates. The S$5,000 floor exclusion is T5's job, not this engine's.
    """

    year: int
    month: int                              # 1-12
    basic_salary: float                     # basic monthly salary ONLY (PRD §6)
    hours: float                            # project hours that month (PRD §6)
    period_start: Optional[date] = None     # involvement∩claim window start (joiner)
    period_end: Optional[date] = None       # involvement∩claim window end (leaver)


# ---------------------------------------------------------------------------
# Per-month components (full precision — no rounding here)
# ---------------------------------------------------------------------------
def _capped_salary(basic_salary: float, cap: float) -> float:
    """``min(basic_salary, cap)`` — the arithmetic cap clamp (PRD §6, not a gate)."""
    return min(basic_salary, cap)


def _time_contribution(hours: float, year: int, month: int, hours_per_day: float) -> float:
    """``min(1, hours / (weekdays(m) × hours_per_day))`` (PRD §6).

    Clamped to ``[0, 1]``: hours over the weekday capacity do not over-claim
    (ANS-006 warning case), and zero hours give 0.0 (ANS-005 New-Hire-no-hours
    -> Method A qualifying cost 0). Full precision; no rounding.
    """
    capacity = weekdays_in_month(year, month) * hours_per_day
    if capacity <= 0:  # defensive; a Gregorian month always has weekday capacity
        return 0.0
    return min(1.0, hours / capacity)


def _month_breakdown(m: ClaimableMonth, cfg: Config) -> MonthlyBreakdownA:
    """Compute the full-precision per-month breakdown for one claimable month."""
    capped = _capped_salary(m.basic_salary, cfg.salary_cap)

    # month_fraction: 1.0 over a whole month; otherwise overlap / weekdays(m).
    # If no involvement window is supplied, the whole calendar month is claimed.
    if m.period_start is None and m.period_end is None:
        fraction = 1.0
    else:
        # Default an open endpoint to the month's own boundary so a one-sided
        # window (e.g. only a join date) clips correctly.
        import calendar as _calendar

        last_day = _calendar.monthrange(m.year, m.month)[1]
        p_start = m.period_start or date(m.year, m.month, 1)
        p_end = m.period_end or date(m.year, m.month, last_day)
        fraction = _month_fraction(m.year, m.month, p_start, p_end)

    time_contrib = _time_contribution(m.hours, m.year, m.month, cfg.hours_per_day)

    # FULL PRECISION — do NOT round the per-month qualifying cost (PRD §6).
    qualifying_cost = capped * fraction * time_contrib

    return MonthlyBreakdownA(
        year=m.year,
        month=m.month,
        capped_salary=capped,
        month_fraction=fraction,
        time_contribution=time_contrib,
        qualifying_cost=qualifying_cost,
    )


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
def _apply_upskill_cap(
    breakdown: list, hire_type: Optional[HireType], cfg: Config
) -> tuple:
    """Cap existing-staff (upskill/reskill to PL3) to ``upskill_max_months`` months.

    EDB Support Package: new hires are funded across the qualifying period, but
    existing staff re/upskilling to PL3 are funded for **up to 9 months only**.
    New hires (and unknown hire types) are never capped. The 9 kept months are
    the earliest qualifying ones (anchor ``first_qualifying``, ASSUMED/configurable
    — the ``training_start`` anchor is pending Letter-of-Award confirmation).
    Returns ``(kept_breakdown, months_capped)``; kept rows preserve input order.
    """
    cap = getattr(cfg, "upskill_max_months", 0) or 0
    is_existing = hire_type in (HireType.UPSKILLED, HireType.RESKILLED)
    if not is_existing or cap <= 0 or len(breakdown) <= cap:
        return breakdown, 0
    earliest = sorted(range(len(breakdown)), key=lambda i: (breakdown[i].year, breakdown[i].month))
    keep = set(earliest[:cap])
    kept = [b for i, b in enumerate(breakdown) if i in keep]
    return kept, len(breakdown) - len(kept)


def compute_method_a(
    employee_id: str,
    months: Iterable[ClaimableMonth],
    *,
    config: Optional[Config] = None,
    hire_type: Optional[HireType] = None,
) -> MethodAResult:
    """Compute the Method A (EDB pro-ration) claim for one employee.

    Sums ``capped_salary × month_fraction × time_contribution`` over the given
    claimable months at full precision, then rounds ONLY the final claim amount
    (``round(qualifying_cost_total × support_rate, 2)`` — the template's
    ``ROUND(G×H, 2)``). The full monthly breakdown is retained (FR-4).

    The months are taken as given — the engine runs no eligibility gates (T5
    owns that). Order of the returned breakdown follows the input order.

    Args:
        employee_id: trainee identifier (carried onto the result for FR-7/-13).
        months: the claimable person-months (capped-eligible, in claim window).
        config: tunables (support_rate, salary_cap, hours_per_day). Defaults to
            the canonical :data:`edb_claim.config.settings`.

    Returns:
        :class:`MethodAResult` with full breakdown, full-precision qualifying
        cost total, and the cent-rounded ``claim_amount``.
    """
    cfg = config if config is not None else settings

    breakdown: list[MonthlyBreakdownA] = [_month_breakdown(m, cfg) for m in months]

    # Existing-staff (upskill/reskill to PL3) 9-month cap (EDB Support Package).
    breakdown, months_capped = _apply_upskill_cap(breakdown, hire_type, cfg)

    # Full-precision sum; NOT pre-rounded (PRD §6 cent rule).
    qualifying_cost_total = sum(b.qualifying_cost for b in breakdown)

    # Round ONLY the final claim, like the template column I = ROUND(G*H, 2).
    claim_amount = round(qualifying_cost_total * cfg.support_rate, 2)

    return MethodAResult(
        employee_id=employee_id,
        qualifying_cost_total=qualifying_cost_total,
        support_rate=cfg.support_rate,
        claim_amount=claim_amount,
        monthly=tuple(breakdown),
        months_capped=months_capped,
    )


def compute_method_a_from_person_months(
    employee_id: str,
    person_months: Sequence,
    *,
    year: int,
    salary_by_month: Optional[dict] = None,
    basic_salary: Optional[float] = None,
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    config: Optional[Config] = None,
    hire_type: Optional[HireType] = None,
) -> MethodAResult:
    """Adapter: build :class:`ClaimableMonth` inputs from T2 ``PersonMonth`` rows.

    The Time Sheet (T2) emits ``PersonMonth`` rows carrying hours but ``year=0``
    and ``basic_salary=0.0`` (year is implied by the claim window; salary comes
    from T3 payroll). This convenience adapter stamps the claim ``year``, joins
    the basic salary (per-month via ``salary_by_month`` or a flat
    ``basic_salary``), and applies one involvement window, then delegates to
    :func:`compute_method_a`. Eligibility filtering (T5) is the caller's job —
    pass only the claimable months.
    """
    claimable: list[ClaimableMonth] = []
    for pm in person_months:
        if salary_by_month is not None:
            sal = salary_by_month.get(pm.month)
            if sal is None:
                sal = basic_salary if basic_salary is not None else pm.basic_salary
        elif basic_salary is not None:
            sal = basic_salary
        else:
            sal = pm.basic_salary
        pm_year = year if getattr(pm, "year", 0) in (0, None) else pm.year
        claimable.append(
            ClaimableMonth(
                year=pm_year,
                month=pm.month,
                basic_salary=sal,
                hours=pm.hours,
                period_start=period_start,
                period_end=period_end,
            )
        )
    return compute_method_a(employee_id, claimable, config=config, hire_type=hire_type)
