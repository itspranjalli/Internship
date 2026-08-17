"""FR-14 evaluation harness — scores LLM outputs against the §8 ground truth.

The registry is deliberately wider than what is implemented: PRD FR-14 names four
scorers (extraction field accuracy, designation precision/recall, reconciliation
match accuracy, and Q&A groundedness). **Only ``qa_groundedness`` is implemented**;
the other three are registered as explicit ``not_implemented`` stubs so the report
shape is stable and completing T24 later is an addition, not a refactor.

Run it::

    python -m edb_claim.eval                     # offline
    EDB_LLM_BASE_URL=... python -m edb_claim.eval  # with the local model connected

Offline is the trivial case (the assistant returns retrieved text verbatim); the
model-connected run is the one that can fail, so the two are reported separately.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Sequence

from edb_claim.config import Config, settings
from edb_claim.eval.groundedness import allowed_figures, check, extract_figures
from edb_claim.eval.questions import EvalQuestion, questions

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SAMPLE = os.path.join(_REPO_ROOT, "sample_data")

_CENT = Decimal("0.01")


# ---------------------------------------------------------------------------
@dataclass
class QuestionOutcome:
    id: str
    question: str
    case: str
    passed: bool
    grounded: bool
    mode: str
    used_model: bool
    failures: List[str] = field(default_factory=list)
    unsupported_figures: List[str] = field(default_factory=list)
    confidence: Optional[float] = None
    confidence_reason: Optional[str] = None
    answer: str = ""


@dataclass
class ScorerResult:
    name: str
    status: str                       # ok | not_implemented
    score: Optional[float] = None     # 0-1
    passed: int = 0
    total: int = 0
    note: str = ""
    outcomes: List[QuestionOutcome] = field(default_factory=list)


@dataclass
class EvalReport:
    mode: str                          # offline | model
    model: Optional[str]
    scorers: List[ScorerResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"mode": self.mode, "model": self.model,
                "scorers": [asdict(s) for s in self.scorers]}


# ---------------------------------------------------------------------------
def build_result(sample_dir: str = _SAMPLE) -> Any:
    """Run the deterministic pipeline over the §8 fixtures (the ground truth)."""
    from edb_claim.app.pipeline import run_pipeline

    return run_pipeline(
        [os.path.join(sample_dir, "internal_ANS.xlsx"),
         os.path.join(sample_dir, "internal_DSG.xlsx")],
        os.path.join(sample_dir, "rse_list.xlsx"),
        os.path.join(sample_dir, "payroll.xlsx"),
    )


def _quotes(answer_text: str, figure: float) -> bool:
    """True if the answer states ``figure`` to the cent."""
    target = Decimal(str(round(figure, 2)))
    return any(abs(d - target) <= _CENT for d in extract_figures(answer_text))


def score_qa_groundedness(
    result: Any,
    assistant: Any,
    qs: Sequence[EvalQuestion],
    *,
    config: Config = settings,
) -> ScorerResult:
    """FR-14's Q&A groundedness: every figure in an answer must trace to a row.

    A question passes only if all of these hold: the answer is grounded (measured
    by the same :func:`~edb_claim.eval.groundedness.check` the app runs at
    runtime), it took the expected route, and it quotes the expected figure.
    """
    outcomes: List[QuestionOutcome] = []
    for q in qs:
        failures: List[str] = []
        try:
            ans = assistant.answer(q.question, result)
        except Exception as exc:  # noqa: BLE001 — a crash is a failed question
            outcomes.append(QuestionOutcome(
                q.id, q.question, q.case, passed=False, grounded=False, mode="error",
                used_model=False, failures=[f"assistant raised: {exc}"]))
            continue

        if ans.grounded is not q.expect_grounded:
            failures.append(
                f"grounded={ans.grounded}, expected {q.expect_grounded}"
                + (f" — unsupported: {', '.join(ans.unsupported_figures)}"
                   if ans.unsupported_figures else "")
            )
        if q.expect_mode and ans.mode != q.expect_mode:
            failures.append(f"routed to '{ans.mode}', expected '{q.expect_mode}'")
        if q.expect_figure is not None:
            expected = q.expect_figure(result)
            if not _quotes(ans.text, expected):
                failures.append(f"does not quote the pipeline figure {expected:,.2f}")
        for needle in q.expect_substrings:
            if needle.lower() not in ans.text.lower():
                failures.append(f"missing expected phrase '{needle}'")

        # FR-14: an ungrounded or low-confidence answer must carry an explanation.
        low_conf = (ans.confidence is not None
                    and ans.confidence < config.confidence_cutoff)
        if (not ans.grounded or low_conf) and not ans.confidence_reason:
            failures.append("no plain-language reason surfaced (FR-14)")

        outcomes.append(QuestionOutcome(
            id=q.id, question=q.question, case=q.case, passed=not failures,
            grounded=ans.grounded, mode=ans.mode, used_model=ans.used_model,
            failures=failures, unsupported_figures=list(ans.unsupported_figures),
            confidence=ans.confidence, confidence_reason=ans.confidence_reason,
            answer=ans.text,
        ))

    passed = sum(1 for o in outcomes if o.passed)
    return ScorerResult(
        name="qa_groundedness", status="ok",
        score=(passed / len(outcomes)) if outcomes else 1.0,
        passed=passed, total=len(outcomes),
        note="every figure in an answer must trace to a claim row, stored record "
             "or retrieved scheme fact (PRD FR-12/FR-14)",
        outcomes=outcomes,
    )


def _stub(name: str, note: str) -> Callable[..., ScorerResult]:
    def scorer(result: Any, assistant: Any, qs: Sequence[EvalQuestion],
               *, config: Config = settings) -> ScorerResult:
        return ScorerResult(name=name, status="not_implemented", note=note)
    return scorer


SCORERS: Dict[str, Callable[..., ScorerResult]] = {
    "qa_groundedness": score_qa_groundedness,
    "extraction": _stub(
        "extraction",
        "FR-14 extraction field accuracy vs §8 ground truth — not implemented "
        "(scope: Q&A groundedness only)"),
    "designation": _stub(
        "designation",
        "FR-14 G5 designation precision/recall on the non-qualifying categories — "
        "not implemented (scope: Q&A groundedness only)"),
    "reconciliation": _stub(
        "reconciliation",
        "FR-14 cross-document match accuracy (§8 case 12 name variants) — "
        "not implemented (scope: Q&A groundedness only)"),
}


# ---------------------------------------------------------------------------
def run(
    scorers: Optional[Sequence[str]] = None,
    *,
    result: Any = None,
    assistant: Any = None,
    config: Config = settings,
    include_adversarial: bool = True,
) -> EvalReport:
    """Score the assistant and return the report.

    ``result``/``assistant`` are injectable for tests; by default the harness
    builds both from the §8 fixtures.
    """
    if result is None:
        result = build_result()
    if assistant is None:
        from edb_claim.llm.qa import AuditAssistant
        assistant = AuditAssistant(config=config)

    live = bool(getattr(assistant, "client", None)) and config.llm_enabled
    report = EvalReport(mode="model" if live else "offline",
                        model=config.llm_model if live else None)
    qs = questions(include_adversarial=include_adversarial)
    for name in (scorers or SCORERS.keys()):
        scorer = SCORERS.get(name)
        if scorer is None:
            raise KeyError(f"unknown scorer: {name}")
        report.scorers.append(scorer(result, assistant, qs, config=config))

    # A configured endpoint that never answered (down, or every call cache-missed)
    # is NOT a model run — say so rather than let the header imply coverage.
    if live and not any(o.used_model for s in report.scorers for o in s.outcomes):
        report.mode = "offline (endpoint configured but no answer came from it)"
    return report


# ---------------------------------------------------------------------------
def format_report(report: EvalReport) -> str:
    lines: List[str] = []
    lines.append("=" * 78)
    lines.append(f"FR-14 evaluation — mode: {report.mode}"
                 + (f" ({report.model})" if report.model else ""))
    lines.append("=" * 78)
    for s in report.scorers:
        if s.status != "ok":
            lines.append(f"\n  {s.name:<18} NOT IMPLEMENTED — {s.note}")
            continue
        pct = (s.score or 0) * 100
        lines.append(f"\n  {s.name:<18} {s.passed}/{s.total} passed  ({pct:.1f}%)")
        lines.append(f"  {'':<18} {s.note}")
        grounded = sum(1 for o in s.outcomes if o.grounded)
        lines.append(f"  {'':<18} grounded answers: {grounded}/{len(s.outcomes)}")
        # Be explicit about how many answers a model actually phrased. Offline
        # answers are trivially grounded (they are retrieved text verbatim), so a
        # 100% score over 0 model answers proves nothing about the model.
        by_model = sum(1 for o in s.outcomes if o.used_model)
        lines.append(f"  {'':<18} phrased by the model: {by_model}/{len(s.outcomes)}"
                     + ("  ← the rest are deterministic/offline answers, which are "
                        "grounded by construction" if by_model < len(s.outcomes) else ""))
        failed = [o for o in s.outcomes if not o.passed]
        if failed:
            lines.append("\n  Failures:")
            for o in failed:
                lines.append(f"    ✗ [{o.id}] {o.question}")
                lines.append(f"        case: {o.case or '—'}")
                for f in o.failures:
                    lines.append(f"        · {f}")
        else:
            lines.append("\n  All questions passed.")
    lines.append("")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m edb_claim.eval",
                                 description="FR-14 response evaluation harness")
    ap.add_argument("--scorer", action="append", dest="scorers",
                    help="scorer to run (repeatable); default: all")
    ap.add_argument("--json", dest="json_path", default="eval_report.json",
                    help="where to write the machine-readable report")
    ap.add_argument("--no-adversarial", action="store_true",
                    help="skip the adversarial questions")
    args = ap.parse_args(argv)

    report = run(args.scorers, include_adversarial=not args.no_adversarial)
    print(format_report(report))
    with open(args.json_path, "w", encoding="utf-8") as fh:
        json.dump(report.to_dict(), fh, indent=2)
    print(f"  report written to {args.json_path}\n")

    qa = next((s for s in report.scorers if s.name == "qa_groundedness"), None)
    return 0 if (qa is None or qa.passed == qa.total) else 1
