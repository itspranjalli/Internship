"""AI advisory post-pass over a completed pipeline result (FR-9/10/11 + FR-14).

The deterministic pipeline (``app/pipeline.py``) computes every figure with the
model offline — it imports nothing from ``llm/``. This module is the *opposite*
direction: it runs **after** the pipeline, reads its result by duck-typing, and
attaches LLM **advisories** (designation judgements, cross-document match
proposals, optional payslip-extraction cross-checks). Nothing here changes a
claim figure or a verdict; advisories are surfaced to HR to confirm or override
(the hard boundary — LLM proposes, Python disposes).

Cheap by construction and deterministic on rerun: only the borderline G5 cases
the gates flagged are judged, only non-exact name matches are sent to the model,
and every call is cached (§9). With no endpoint the bundle is ``enabled=False``
and empty, so the app renders an "offline" note and is otherwise unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from edb_claim.config import Config, settings
from edb_claim.llm.client import LLMClient
from edb_claim.llm.designation import DesignationJudgement, judge_review_cases
from edb_claim.llm.extract import (
    ExtractionCrossCheck,
    cross_check,
    extract_payroll_register,
)
from edb_claim.llm.reconcile import MatchProposal, reconcile_result


@dataclass(frozen=True)
class AiAdvisories:
    """Bundle of model proposals attached to a pipeline result (read-only)."""

    enabled: bool                                            # an endpoint was reachable
    designations: Dict[str, DesignationJudgement] = field(default_factory=dict)
    matches: Tuple[MatchProposal, ...] = ()                  # exact + queued
    extraction_checks: Tuple[ExtractionCrossCheck, ...] = ()

    # -- convenience views for the UI ------------------------------------
    @property
    def match_queue(self) -> Tuple[MatchProposal, ...]:
        """Name/fuzzy matches awaiting HR confirmation (FR-11)."""
        return tuple(m for m in self.matches if m.needs_confirmation)

    @property
    def disagreements(self) -> Tuple[DesignationJudgement, ...]:
        """G5 judgements where the model differs from the deterministic gate."""
        return tuple(j for j in self.designations.values() if not j.agrees_with_gate)

    @property
    def extraction_mismatches(self) -> Tuple[ExtractionCrossCheck, ...]:
        return tuple(c for c in self.extraction_checks if not c.agrees)


def build_advisories(
    result: Any,
    *,
    rse_records: Sequence[Any] = (),
    payroll_path: Optional[str] = None,
    run_extraction: bool = False,
    extraction_limit: Optional[int] = 12,
    client: Optional[LLMClient] = None,
    config: Config = settings,
) -> AiAdvisories:
    """Run the advisory passes that are cheap by default.

    ``run_extraction`` is opt-in (one model call per payroll row) so the default
    post-analysis pass stays fast; the UI triggers it on demand. Returns an empty,
    disabled bundle when no model is configured.
    """
    use_client = client if client is not None else _safe_client(config)
    enabled = use_client is not None and config.llm_enabled
    if not enabled:
        return AiAdvisories(enabled=False)

    designations = judge_review_cases(result, client=use_client, config=config)
    matches = tuple(reconcile_result(result, rse_records, client=use_client, config=config))

    checks: Tuple[ExtractionCrossCheck, ...] = ()
    if run_extraction and payroll_path:
        extracted = extract_payroll_register(
            payroll_path, limit=extraction_limit, client=use_client, config=config)
        salary_records = _collect_salary_records(result)
        checks = tuple(cross_check(extracted, salary_records, config=config))

    return AiAdvisories(
        enabled=True,
        designations=designations,
        matches=matches,
        extraction_checks=checks,
    )


def _collect_salary_records(result: Any) -> Tuple[Any, ...]:
    """Best-effort gather of SalaryRecord-like rows for the extraction cross-check.

    The pipeline result doesn't retain raw SalaryRecords, but each employee's
    Method A monthly breakdown + the modal basic give us (id, year, month, basic)
    tuples to compare against. We synthesise light records duck-typed to what
    ``extract.cross_check`` reads (employee_id, year, month, basic_salary).
    """
    from types import SimpleNamespace

    recs: List[Any] = []
    for e in getattr(result, "all_employees", ()):
        basic = e.monthly_basic_salary
        if basic is None:
            continue
        for mb in getattr(e.method_a, "monthly", ()):
            recs.append(SimpleNamespace(
                employee_id=e.employee.id, year=mb.year, month=mb.month,
                basic_salary=basic))
    return tuple(recs)


def _safe_client(config: Config) -> Optional[LLMClient]:
    try:
        return LLMClient(config)
    except Exception:
        return None
