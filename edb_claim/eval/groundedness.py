"""Measure whether an answer's figures trace back to real rows (FR-12/FR-14).

The rule this module enforces is PRD FR-13's hard boundary: *the LLM may not emit
any figure absent from a retrieved structured row*. Concretely:

1. :func:`extract_figures` pulls every number out of the answer text.
2. :func:`allowed_figures` builds the ground set — the pipeline result, the
   persisted store rows, the retrieved scheme context, and the config constants.
3. :func:`check` reports which figures (if any) are unsupported, with a
   plain-language reason HR can read.

A failed check never suppresses an answer (FR-14). It annotates it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, List, Optional, Sequence, Set, Tuple

from edb_claim.config import Config, settings

# A money/percentage/plain number, optionally prefixed S$ or $ and with thousands
# separators. Bold markers (**$1,234.00**) are stripped by the caller's regex
# boundaries since ** is not a digit.
#
# The second lookbehind drops the numeric tail of an employee id (ANS-001,
# EMP-4521): those are identifiers, not figures. Without it a roster with
# four-digit ids would flag every correct structured answer as "unverified" —
# and a false warning is worse than none, because HR learns to ignore the badge.
# A range like "$20,000-$25,000" is unaffected: the char before the hyphen is a
# digit, not a letter.
_NUMBER_RE = re.compile(
    r"(?<![\w.])(?<![A-Za-z]-)(?:S?\$\s*)?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
)

# Numbers that carry no claim-figure meaning and would only create false alarms:
# small counts (roster sizes, month counts, gate numbers G1-G7), calendar years,
# and the ordinals that appear in ordinary prose.
_SMALL_INT_MAX = Decimal(12)
_YEAR_MIN, _YEAR_MAX = Decimal(1990), Decimal(2100)

_DEFAULT_TOLERANCE = Decimal("0.01")


@dataclass(frozen=True)
class GroundednessReport:
    """The verdict on one answer. ``reason`` is written for HR, not for logs."""

    grounded: bool
    figures: List[Decimal] = field(default_factory=list)
    unsupported: List[Decimal] = field(default_factory=list)
    reason: Optional[str] = None

    @property
    def score(self) -> float:
        """Fraction of the answer's figures that trace to a row (1.0 if none)."""
        if not self.figures:
            return 1.0
        return (len(self.figures) - len(self.unsupported)) / len(self.figures)


# ---------------------------------------------------------------------------
# 1. figures in the answer
# ---------------------------------------------------------------------------
def extract_figures(text: str) -> List[Decimal]:
    """Every number in ``text`` as a :class:`Decimal`, in order of appearance.

    Handles ``$7,310.87``, ``S$20,000``, ``60%`` and bare decimals. Duplicates are
    kept — an answer that repeats an invented figure twice is twice as wrong.
    """
    out: List[Decimal] = []
    for raw in _NUMBER_RE.findall(text or ""):
        try:
            out.append(Decimal(raw.replace(",", "")))
        except InvalidOperation:  # pragma: no cover — regex already constrains this
            continue
    return out


def _is_trivial(value: Decimal) -> bool:
    """True for numbers that cannot be a claim figure (counts, years, 0/1)."""
    if value != value.to_integral_value():
        return False
    if value <= _SMALL_INT_MAX:
        return True
    return _YEAR_MIN <= value <= _YEAR_MAX


# ---------------------------------------------------------------------------
# 2. the ground set
# ---------------------------------------------------------------------------
def _add(sink: Set[Decimal], value: Any) -> None:
    """Add one numeric fact in every form an answer might legitimately render it."""
    if value is None or isinstance(value, bool):
        return
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return
    sink.add(d)
    # a rate stored as 0.60 is rendered "60%"; hours 8.8 stays 8.8
    if d != 0 and abs(d) <= 1:
        sink.add(d * 100)
    # figures are rendered rounded to the cent, and sometimes to whole dollars
    sink.add(round(d, 2))
    sink.add(d.to_integral_value())


def _from_method(sink: Set[Decimal], method: Any) -> None:
    if method is None:
        return
    _add(sink, getattr(method, "claim_amount", None))
    _add(sink, getattr(method, "qualifying_cost_total", None))
    _add(sink, getattr(method, "support_rate", None))
    for m in getattr(method, "monthly", ()) or ():
        for attr in ("capped_salary", "qualifying_cost", "month_fraction",
                     "time_contribution", "b_capped_salary", "d1_capacity_hours",
                     "d2_project_hours", "d3_time_contribution", "e_qualifying_cost"):
            _add(sink, getattr(m, attr, None))


def _from_result(sink: Set[Decimal], result: Any) -> None:
    """Every figure the deterministic pipeline computed — the primary ground set."""
    if result is None:
        return
    _add(sink, getattr(result, "total_claim_a", None))
    _add(sink, getattr(result, "total_claim_b", None))
    _add(sink, getattr(result, "support_rate", None))
    for e in getattr(result, "all_employees", ()) or ():
        _from_method(sink, getattr(e, "method_a", None))
        _from_method(sink, getattr(e, "method_b", None))
        _add(sink, getattr(e, "monthly_basic_salary", None))
        rollup = getattr(e, "rollup", None)
        for attr in ("total_hours", "total_project_hours"):
            _add(sink, getattr(rollup, attr, None))


def _from_db(sink: Set[Decimal], conn: Any, employee_id: Optional[str]) -> None:
    """Figures from the persisted store — the FR-13 exact-SQL retrieval path."""
    if conn is None or not employee_id:
        return
    try:
        from edb_claim.db.store import get_calc, get_person_months
    except Exception:  # pragma: no cover — store is optional
        return
    for method in ("A", "B"):
        try:
            calc = get_calc(conn, employee_id, method)
        except Exception:
            continue
        if not calc:
            continue
        for key in ("claim_amount", "qualifying_cost_total", "support_rate"):
            _add(sink, calc.get(key))
        for m in calc.get("monthly") or ():
            if isinstance(m, dict):
                for v in m.values():
                    _add(sink, v)
    try:
        for row in get_person_months(conn, employee_id):
            for v in dict(row).values():
                _add(sink, v)
    except Exception:
        return


def _from_context(sink: Set[Decimal], context: Any) -> None:
    """Numbers appearing verbatim in retrieved text are legitimately grounded.

    ``context`` may be a string, or the ``(id, title, text)`` triples returned by
    the assistant's ``_retrieve``.
    """
    if context is None:
        return
    if isinstance(context, str):
        for d in extract_figures(context):
            _add(sink, d)
        return
    if isinstance(context, (tuple, list, set)):
        for item in context:
            _from_context(sink, item)  # nested KB triples / mixed sequences
        return
    _from_context(sink, str(context))


def _from_config(sink: Set[Decimal], config: Config) -> None:
    for attr in ("salary_floor", "salary_cap", "support_rate", "hours_per_day",
                 "max_grant_amount", "disbursement_threshold_pct",
                 "min_claim_months", "upskill_max_months",
                 "audit_report_interval_months", "final_submission_days",
                 "confidence_cutoff", "variance_material_pct"):
        _add(sink, getattr(config, attr, None))


def allowed_figures(
    result: Any = None,
    retrieved_context: Any = None,
    *,
    db_conn: Any = None,
    employee_id: Optional[str] = None,
    config: Config = settings,
    extra: Iterable[Any] = (),
) -> Set[Decimal]:
    """The set of figures an answer may legitimately contain.

    Union of: the live :class:`~edb_claim.app.pipeline.PipelineResult`, the
    persisted rows for ``employee_id``, numerals in the retrieved scheme context,
    and the config constants. Anything outside this set is unsupported.
    """
    sink: Set[Decimal] = set()
    _from_result(sink, result)
    _from_db(sink, db_conn, employee_id)
    _from_context(sink, retrieved_context)
    _from_config(sink, config)
    for value in extra:
        _add(sink, value)
    return sink


# ---------------------------------------------------------------------------
# 3. the check
# ---------------------------------------------------------------------------
def _derivable(
    value: Decimal,
    bases: Set[Decimal],
    rates: Set[Decimal],
    tolerance: Decimal,
) -> bool:
    """The one arithmetic the FR-12 prompt explicitly permits, and nothing more.

    The assistant may "apply the $20,000 cap and the 60% support rate to a salary
    the user names". So the *bases* are deliberately narrow — the figures in the
    question plus the salary cap/floor — and the *rates* are the scheme rates.

    Widening `bases` to the whole allowed set (every employee's claim amount)
    would make almost any 5-figure number derivable from some row × 0.6, which is
    exactly the hallucination this check exists to catch.
    """
    for base in bases:
        for rate in rates:
            for candidate in (base * rate, base * (1 - rate)):
                if abs(candidate - value) <= tolerance:
                    return True
    return False


def derivation_bases(
    question: str, *, config: Config = settings
) -> Tuple[Set[Decimal], Set[Decimal]]:
    """``(bases, rates)`` for the permitted cap-then-rate derivation.

    Bases: the figures the user named in the question (a hypothetical salary),
    clamped to the cap, plus the cap and floor themselves. Rates: the support rate.
    """
    bases: Set[Decimal] = set()
    cap = Decimal(str(config.salary_cap))
    for d in extract_figures(question):
        if _is_trivial(d):
            continue
        bases.add(d)
        bases.add(min(d, cap))          # the capped form is the answerable one
    bases.add(cap)
    bases.add(Decimal(str(config.salary_floor)))
    rates = {Decimal(str(config.support_rate))}
    return bases, rates


def _phrase(values: Sequence[Decimal]) -> str:
    def fmt(d: Decimal) -> str:
        return f"{d:,.2f}" if d != d.to_integral_value() else f"{d:,.0f}"
    shown = [fmt(v) for v in values[:3]]
    tail = "" if len(values) <= 3 else f" (and {len(values) - 3} more)"
    return ", ".join(shown) + tail


def check(
    answer_text: str,
    allowed: Set[Decimal],
    *,
    derive_bases: Optional[Set[Decimal]] = None,
    derive_rates: Optional[Set[Decimal]] = None,
    tolerance: Decimal = _DEFAULT_TOLERANCE,
) -> GroundednessReport:
    """Score ``answer_text`` against ``allowed``.

    Pass ``derive_bases``/``derive_rates`` (from :func:`derivation_bases`) to admit
    the cap-then-rate arithmetic the FR-12 prompt permits. Omit them and only
    figures present verbatim in a row or the retrieved context are accepted.

    Returns a report whose ``reason`` is plain language for HR — FR-14 requires the
    explanation to travel with the answer, so the caller must surface it rather
    than log it.
    """
    bases = derive_bases or set()
    rates = derive_rates or set()
    figures = extract_figures(answer_text)
    unsupported: List[Decimal] = []
    for value in figures:
        if _is_trivial(value):
            continue
        if any(abs(value - a) <= tolerance for a in allowed):
            continue
        if bases and rates and _derivable(value, bases, rates, tolerance):
            continue
        unsupported.append(value)

    if not unsupported:
        return GroundednessReport(grounded=True, figures=figures)

    reason = (
        f"This answer mentions {_phrase(unsupported)}, which does not appear in any "
        "claim row, source document or scheme rule retrieved for this question. "
        "Treat the figure as unverified and check it against the Claim amount "
        "screen before relying on it."
    )
    return GroundednessReport(
        grounded=False, figures=figures, unsupported=unsupported, reason=reason
    )
