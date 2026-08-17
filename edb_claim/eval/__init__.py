"""FR-14 response evaluation — groundedness scoring for the Q&A assistant (T24).

Two consumers share one core so that what the harness scores is exactly what the
app enforces:

* **runtime** — :mod:`edb_claim.llm.qa` verifies every model-phrased answer before
  returning it, setting ``Answer.grounded`` and a plain-language
  ``confidence_reason``. Nothing is ever discarded (PRD FR-14: "no black box,
  nothing discarded") — a failed check annotates the answer, it does not suppress it.
* **offline** — :mod:`edb_claim.eval.harness` scores a question set against the §8
  synthetic fixtures and records the metrics per run.

Groundedness is defined by PRD FR-12/FR-13: *every figure in an answer must trace
to a row in the FR-13 store* (or to the retrieved scheme context). It is measured,
never asserted.
"""

from edb_claim.eval.groundedness import (  # noqa: F401
    GroundednessReport,
    allowed_figures,
    check,
    derivation_bases,
    extract_figures,
)

__all__ = ["GroundednessReport", "allowed_figures", "check", "derivation_bases",
           "extract_figures"]
