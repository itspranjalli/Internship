"""Tests for edb_claim.domain.calendar_utils — the working-day oracle (PRD §6).

Asserts the EDB worked-example facts from the ``Salary Pro-ration E.g.`` sheet
(9,500 over 15 Jan-31 Mar 2018, 13/23 partial first month) plus edge cases.

Runs under pytest (`.venv/bin/python -m pytest tests/test_calendar_utils.py -q`)
OR, when pytest is absent, directly: `python tests/test_calendar_utils.py`
(plain-assert harness at the bottom).
"""

import os
import sys
from datetime import date

# Allow `python tests/test_calendar_utils.py` from anywhere: ensure the repo
# root (parent of tests/) is importable. Under pytest this is a harmless no-op.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from edb_claim.domain.calendar_utils import (
    month_fraction,
    networkdays,
    weekdays_in_month,
    worked_weekdays,
)


# --- EDB worked-example oracle (PRD §6 / PLAN cent-level note) --------------
def test_weekdays_in_jan_2018_is_23():
    # Jan 2018: Mon 1st .. Wed 31st -> 23 weekdays (EDB example denominator).
    assert weekdays_in_month(2018, 1) == 23


def test_worked_weekdays_15_to_31_jan_2018_is_13():
    # EDB example partial-month numerator: 15-31 Jan 2018 inclusive -> 13.
    assert worked_weekdays(date(2018, 1, 15), date(2018, 1, 31)) == 13


def test_month_fraction_partial_jan_2018_is_13_over_23():
    assert month_fraction(2018, 1, date(2018, 1, 15), date(2018, 1, 31)) == 13 / 23


def test_month_fraction_full_month_is_one():
    # Feb and Mar 2018 are fully covered by the 15 Jan - 31 Mar window -> 1.0.
    assert month_fraction(2018, 2, date(2018, 1, 15), date(2018, 3, 31)) == 1.0
    assert month_fraction(2018, 3, date(2018, 1, 15), date(2018, 3, 31)) == 1.0


def test_month_fraction_exactly_full_month_window_is_one():
    # Window equal to the calendar month -> exactly 1.0 (no 20/20 float drift).
    assert month_fraction(2018, 2, date(2018, 2, 1), date(2018, 2, 28)) == 1.0


# --- NETWORKDAYS parity with Excel -----------------------------------------
def test_networkdays_matches_excel_known_range():
    # Excel: =NETWORKDAYS(DATE(2018,1,15), DATE(2018,1,31)) -> 13.
    assert networkdays(date(2018, 1, 15), date(2018, 1, 31)) == 13


def test_networkdays_full_month_equals_weekdays_in_month():
    # For a full calendar month, NETWORKDAYS == weekdays_in_month.
    assert networkdays(date(2018, 3, 1), date(2018, 3, 31)) == weekdays_in_month(2018, 3)
    assert networkdays(date(2018, 3, 1), date(2018, 3, 31)) == 22


def test_networkdays_single_weekday_is_one():
    # 15 Jan 2018 is a Monday -> inclusive single-day range counts 1.
    assert networkdays(date(2018, 1, 15), date(2018, 1, 15)) == 1


# --- Edge cases ------------------------------------------------------------
def test_month_with_no_leading_or_trailing_weekend():
    # Jan 2018 starts Mon 1st and ends Wed 31st: no boundary weekend trimming.
    assert worked_weekdays(date(2018, 1, 1), date(2018, 1, 31)) == 23


def test_leap_year_february():
    # Feb 2024 (leap): 29 days -> 21 weekdays.
    assert weekdays_in_month(2024, 2) == 21
    assert worked_weekdays(date(2024, 2, 1), date(2024, 2, 29)) == 21


def test_non_leap_february():
    # Feb 2018: 28 days -> 20 weekdays.
    assert weekdays_in_month(2018, 2) == 20


def test_full_workweek_only():
    # Mon 1 - Fri 5 Jan 2018 -> 5 weekdays; extend to Sun 7 -> still 5.
    assert worked_weekdays(date(2018, 1, 1), date(2018, 1, 5)) == 5
    assert worked_weekdays(date(2018, 1, 1), date(2018, 1, 7)) == 5


def test_weekend_only_range_is_zero():
    # Sat 6 - Sun 7 Jan 2018 -> 0 weekdays.
    assert worked_weekdays(date(2018, 1, 6), date(2018, 1, 7)) == 0


def test_empty_range_is_zero():
    # end before start -> 0 (clamped, not negative).
    assert worked_weekdays(date(2018, 1, 31), date(2018, 1, 1)) == 0
    assert networkdays(date(2018, 1, 31), date(2018, 1, 1)) == 0


def test_month_fraction_no_overlap_is_zero():
    # Window entirely outside the target month -> 0.0.
    assert month_fraction(2018, 1, date(2018, 3, 1), date(2018, 3, 31)) == 0.0


# --- Plain-assert runner (no pytest required) ------------------------------
def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} calendar_utils tests passed.")


if __name__ == "__main__":
    _run_all()
