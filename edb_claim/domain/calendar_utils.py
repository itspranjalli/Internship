"""Working-day / calendar math for the EDB pro-ration (PRD §6, §10 Q5).

Single definition of "working day" used by both calculation methods:

  * **Working days = weekdays (Mon-Fri) only.** Public holidays do NOT reduce
    working days (PRD §6: "the EDB example (13/23 days, Jan 2018) and the
    internal sheet's NETWORKDAYS both exclude weekends only, not public
    holidays"; PRD §10 Q5 ASSUMED, pending auditor confirmation).
  * 8.8 hours/day is applied by the calc engines, not here — these are pure
    *day-count* helpers (config.hours_per_day).

All functions are pure, deterministic, stdlib-only (``datetime`` + ``calendar``),
so identical inputs always yield identical outputs (PRD §9).

Oracle (PRD §6 / PLAN cent-level note, ``Salary Pro-ration E.g.`` sheet):
  weekdays_in_month(2018, 1) == 23  and  worked_weekdays(15 Jan, 31 Jan 2018) == 13,
  giving month_fraction == 13/23 for the partial first month of the 9,500 example.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

# Mon=0 .. Sun=6 (datetime.date.weekday()); Sat=5, Sun=6 are the only excluded days.
_SATURDAY = 5
_SUNDAY = 6


def _is_weekday(d: date) -> bool:
    """True if ``d`` is Mon-Fri (weekends are the only non-working days, PRD §6)."""
    return d.weekday() < _SATURDAY


def worked_weekdays(start_date: date, end_date: date) -> int:
    """Count Mon-Fri in the *inclusive* range ``[start_date, end_date]``.

    Weekends excluded, no public-holiday list (PRD §6). Returns 0 if the range
    is empty (``end_date < start_date``). Both endpoints are counted when they
    are weekdays — this is the partial-month numerator in Method A's
    ``month_fraction`` (PRD §6).
    """
    if end_date < start_date:
        return 0
    count = 0
    d = start_date
    while d <= end_date:
        if _is_weekday(d):
            count += 1
        d += timedelta(days=1)
    return count


def weekdays_in_month(year: int, month: int) -> int:
    """Count of Mon-Fri in the whole calendar month ``year``-``month``.

    This is the denominator of Method A's ``month_fraction`` (PRD §6:
    ``worked_weekdays / total_weekdays(m)``). For Jan 2018 this is 23 (oracle).
    """
    last_day = calendar.monthrange(year, month)[1]
    return worked_weekdays(date(year, month, 1), date(year, month, last_day))


def networkdays(start_date: date, end_date: date) -> int:
    """Excel ``NETWORKDAYS(start, end)`` equivalent — no holiday list.

    Inclusive of both endpoints, weekends excluded (PRD §6). Used by Method B's
    ``[D1] = NETWORKDAYS(date_join, date_left) × 8.8`` (PRD §6). For a full
    calendar month this equals :func:`weekdays_in_month`.

    Excel's NETWORKDAYS counts negative when ``end < start``; we clamp to 0
    here because both calc engines only ever pass forward (join → left) ranges
    and a negative day count is meaningless for pro-ration. (Documented
    divergence from raw Excel for the reversed-range case.)
    """
    return worked_weekdays(start_date, end_date)


def month_fraction(
    year: int,
    month: int,
    period_start: date,
    period_end: date,
) -> float:
    """Method A ``month_fraction(m)`` (PRD §6).

    ``1.0`` when the claim/involvement window ``[period_start, period_end]``
    covers the entire calendar month; otherwise
    ``worked_weekdays(overlap) / weekdays_in_month(month)`` over the overlap of
    the window with the month.

    Returns ``0.0`` when the window does not overlap the month at all. Full
    precision is preserved (no rounding here — PRD §6: only EDB's output
    ``I = ROUND(G×H, 2)`` rounds).
    """
    last_day = calendar.monthrange(year, month)[1]
    month_start = date(year, month, 1)
    month_end = date(year, month, last_day)

    # Overlap of the window with this calendar month (inclusive).
    overlap_start = max(month_start, period_start)
    overlap_end = min(month_end, period_end)
    if overlap_end < overlap_start:
        return 0.0

    # Whole month covered -> exactly 1.0 (avoids 23/23 float drift).
    if overlap_start <= month_start and overlap_end >= month_end:
        return 1.0

    total = weekdays_in_month(year, month)
    if total == 0:  # defensive; a Gregorian month always has weekdays
        return 0.0
    return worked_weekdays(overlap_start, overlap_end) / total
