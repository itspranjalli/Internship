"""Tests for the FR-14 groundedness layer — edb_claim.eval (T24).

Two things must hold, and the second is the one that matters:

1. The checker can tell a real figure from an invented one.
2. When it catches an invention, the answer is **still returned**, annotated with
   a plain-language reason (PRD FR-14: "no black box, nothing discarded"). A
   verifier that silently swallowed bad answers would be a worse failure than the
   hallucination it caught.

A mock transport (the pattern from tests/test_llm_client.py) makes the model path
deterministic with no endpoint. Each case gets a fresh cache directory — the
client caches by prompt, so a shared cache would replay the previous case's
answer instead of the one under test.
"""

import json
import os
import sys
import tempfile
from decimal import Decimal

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from edb_claim.config import Config, settings
from edb_claim.eval.groundedness import (
    allowed_figures,
    check,
    derivation_bases,
    extract_figures,
)
from edb_claim.eval.harness import SCORERS, build_result, run
from edb_claim.llm.cache import LLMCache
from edb_claim.llm.client import LLMClient
from edb_claim.llm.qa import AuditAssistant

_SAMPLE = os.path.join(_REPO_ROOT, "sample_data")

_RESULT = None


def _result():
    global _RESULT
    if _RESULT is None:
        _RESULT = build_result(_SAMPLE)
    return _RESULT


class _CannedTransport:
    """Returns one fixed answer, whatever the prompt."""

    def __init__(self, answer: str, confidence=0.93, reason=None):
        self.answer = answer
        self.confidence = confidence
        self.reason = reason

    def __call__(self, prompt, model, schema, temperature):
        return {"text": json.dumps({"answer": self.answer}),
                "confidence": self.confidence, "confidence_reason": self.reason}


def _assistant_saying(answer: str, confidence=0.93):
    """An assistant whose model is mocked to return ``answer`` verbatim."""
    tmp = tempfile.mkdtemp()
    cfg = Config(llm_base_url="http://mock/v1", llm_model="mock",
                 db_path=os.path.join(tmp, "eval.db"))
    client = LLMClient(cfg, cache=LLMCache(os.path.join(tmp, "cache.json")),
                       transport=_CannedTransport(answer, confidence))
    return AuditAssistant(client=client, config=cfg)


# --- 1. figure extraction --------------------------------------------------
def test_extract_figures_handles_currency_percent_and_decimals():
    got = extract_figures("Claim $7,310.87 at 60% of the S$20,000 cap over 8.8 hours.")
    assert Decimal("7310.87") in got
    assert Decimal("60") in got
    assert Decimal("20000") in got
    assert Decimal("8.8") in got


def test_extract_figures_survives_markdown_emphasis():
    assert Decimal("34200.00") in extract_figures("Claim amount: **$34,200.00** (Method A).")


def test_employee_ids_are_not_read_as_figures():
    """An id is an identifier, not a figure.

    A four-digit id ('EMP-4521') would otherwise be unmatchable against any row
    and flag a perfectly correct answer as unverified — and a false warning is
    worse than none, because HR learns to ignore the badge.
    """
    assert extract_figures("ANS-001 qualifies.") == []
    assert extract_figures("EMP-4521 qualifies.") == []
    # a salary range must still be read
    assert extract_figures("between $20,000-$25,000") == [Decimal("20000"), Decimal("25000")]


# --- 2. the checker --------------------------------------------------------
def test_invented_figure_is_flagged_with_a_reason():
    allowed = allowed_figures(_result(), config=settings)
    rep = check("The claim for this person is $99,123.45.", allowed)
    assert rep.grounded is False
    assert Decimal("99123.45") in rep.unsupported
    assert rep.reason and "99,123.45" in rep.reason
    assert rep.score < 1.0


def test_real_pipeline_figure_is_accepted():
    result = _result()
    emp = next(e for e in result.all_employees if e.employee.id == "ANS-001")
    allowed = allowed_figures(result, config=settings)
    rep = check(f"The claim is ${emp.method_a.claim_amount:,.2f}.", allowed)
    assert rep.grounded is True and rep.score == 1.0


def test_small_counts_and_years_are_not_treated_as_claim_figures():
    """Gate numbers, month counts and years must not raise false alarms.

    The bar is deliberately low (<=12): raising it far enough to absorb a roster
    count of 20 would also absorb an invented '72%' support rate. Larger counts
    are admitted the way the roster path does it — by declaring them as extras.
    """
    rep = check("3 of the 9 months qualify in 2026.", allowed_figures(config=settings))
    assert rep.grounded is True

    roster = "**14 of 20** qualify."
    assert check(roster, allowed_figures(config=settings)).grounded is False
    assert check(roster, allowed_figures(config=settings, extra=[14, 20])).grounded is True


def test_derivation_is_scoped_to_the_question_not_the_whole_roster():
    """60% of a salary the USER named is fine; 60% of someone else's row is not.

    Without this scoping almost any five-figure number is 'derivable' from some
    employee's claim amount, which would defeat the check entirely.
    """
    allowed = allowed_figures(_result(), config=settings)
    bases, rates = derivation_bases("How much of a $25,000 salary counts?")
    ok = check("Capped at $20,000, 60% of that is $12,000.", allowed,
               derive_bases=bases, derive_rates=rates)
    assert ok.grounded is True

    # 22,680 = 37,800 (another employee's claim) x 0.6 — must NOT be admitted.
    bad = check("You can claim $22,680.", allowed,
                derive_bases=bases, derive_rates=rates)
    assert bad.grounded is False


# --- 3. the runtime path: measured, and never discarded --------------------
def test_hallucinated_scheme_answer_is_flagged_but_still_returned():
    hallucination = ("The support rate is 72% and the cap is $31,500 per month.")
    ans = _assistant_saying(hallucination).answer("What is the support rate?", _result())

    assert ans.used_model is True
    assert ans.grounded is False, "an invented rate and cap must not pass as grounded"
    assert set(ans.unsupported_figures) >= {"72.00", "31,500.00"}
    # FR-14: nothing discarded — the original wording survives, annotated.
    assert "72%" in ans.text and "31,500" in ans.text
    assert ans.confidence_reason and "does not appear" in ans.confidence_reason
    assert "Unverified figure" in ans.text


def test_faithful_model_answer_stays_grounded():
    faithful = ("EDB co-funds up to 60% of the basic monthly salary, capped at "
                "$20,000 per month.")
    ans = _assistant_saying(faithful).answer("What is the support rate?", _result())
    assert ans.grounded is True
    assert ans.confidence_reason is None
    assert "Unverified" not in ans.text


def test_low_confidence_answer_carries_a_plain_language_reason():
    """Below the cutoff the answer is kept — with an explanation, per FR-14."""
    ans = _assistant_saying("EDB co-funds up to 60% of basic monthly salary.",
                            confidence=0.42).answer("What is the support rate?", _result())
    assert ans.grounded is True
    assert ans.confidence_reason and "confidence" in ans.confidence_reason.lower()


def test_structured_answers_are_verified_and_fully_confident():
    result = _result()
    ans = AuditAssistant().answer("What is the claim for ANS-004?", result)
    emp = next(e for e in result.all_employees if e.employee.id == "ANS-004")
    assert ans.mode == "data" and ans.grounded is True
    assert f"{emp.method_a.claim_amount:,.2f}" in ans.text
    assert ans.confidence == 1.0


def test_total_answer_is_grounded_to_the_cent():
    result = _result()
    ans = AuditAssistant().answer("What is the total claim?", result)
    assert ans.grounded is True
    assert f"{result.total_claim_a:,.2f}" in ans.text


# --- 4. the harness --------------------------------------------------------
def test_harness_runs_offline_and_reports_all_four_scorers():
    report = run(result=_result())
    assert report.mode == "offline"
    names = {s.name for s in report.scorers}
    assert names == set(SCORERS)

    qa = next(s for s in report.scorers if s.name == "qa_groundedness")
    assert qa.status == "ok" and qa.total > 20
    assert qa.passed == qa.total, (
        "offline groundedness regressed: "
        + "; ".join(f"[{o.id}] {o.failures}" for o in qa.outcomes if not o.passed)
    )

    stubs = [s for s in report.scorers if s.name != "qa_groundedness"]
    assert all(s.status == "not_implemented" and s.score is None for s in stubs)


def test_harness_catches_an_ungrounded_assistant():
    """The harness must FAIL when the model invents — otherwise it tests nothing."""
    liar = _assistant_saying("The support rate is 72% and the cap is $31,500.")
    report = run(["qa_groundedness"], result=_result(), assistant=liar)
    qa = report.scorers[0]
    assert qa.passed < qa.total
    failed = [o for o in qa.outcomes if not o.passed and o.mode == "scheme"]
    assert failed and any(o.unsupported_figures for o in failed)
