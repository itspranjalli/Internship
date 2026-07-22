"""FR-10 — LLM designation judging for gate G5 (PLAN.md T17).

The deterministic G5 gate (``validate/gates.py``) already settles the clear cases:
a whole-word non-qualifying hit ("HR Manager" -> HR) hard-fails, a clearly
technical title ("ML Engineer") cleanly passes. What it *cannot* settle it marks
``needs_review=True`` — a blank title, an ambiguous managerial qualifier
("Engineering Operations Manager"), or a title that is neither clearly technical
nor a clean non-qualifying match. This module refines exactly those flagged cases.

HARD BOUNDARY (CLAUDE.md / PRD §7): the LLM **proposes**, it does not dispose.
The deterministic ``GateResult.passed`` remains the authority for the verdict and
every claim figure; a :class:`DesignationJudgement` is an *advisory* surfaced to
HR with its confidence and a one-line justification (FR-10, FR-14: nothing is a
black box, nothing discarded). HR confirms or overrides in the UI.

It degrades gracefully: with no endpoint configured, judging returns an
``offline`` judgement that simply echoes the deterministic reason, so the app
runs unchanged with the model down (CLAUDE.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from edb_claim.config import Config, settings
from edb_claim.llm.client import LLMClient

# The model returns a category, a proposed qualifies/exclude call, a one-line
# justification and a confidence. All fields are required so the strict
# json-schema path on vLLM yields a fully-populated object.
_JUDGE_SCHEMA = {
    "type": "object",
    "required": ["category", "qualifies", "justification", "confidence"],
    "properties": {
        # one of the non-qualifying categories, or "Technical/R&D", or "Uncertain"
        "category": {"type": "string"},
        # proposed G5 outcome: True = eligible R&D role, False = non-qualifying
        "qualifies": {"type": "boolean"},
        "justification": {"type": "string"},
        "confidence": {"type": "number"},
    },
}


@dataclass(frozen=True)
class DesignationJudgement:
    """One advisory judgement of a free-text designation against G5 (FR-10/FR-14).

    ``proposed_qualifies`` is the model's call; it never overwrites the
    deterministic ``GateResult`` — it is shown alongside it. ``agrees_with_gate``
    lets the UI flag a model/gate disagreement for HR. ``used_model`` is False for
    the offline echo (the deterministic reason verbatim).
    """

    designation: str
    proposed_qualifies: bool          # model's proposed G5 outcome
    category: str                     # EDB category or "Technical/R&D" / "Uncertain"
    justification: str                # one-line, logged per judgement (FR-10)
    confidence: Optional[float]       # 0-1 (FR-9/FR-14)
    deterministic_passed: bool        # the gate's authoritative call (unchanged)
    used_model: bool = False          # False => offline echo of the gate reason
    offline: bool = False             # endpoint not configured

    @property
    def agrees_with_gate(self) -> bool:
        """True when the model's proposal matches the deterministic G5 outcome."""
        return self.proposed_qualifies == self.deterministic_passed

    @property
    def low_confidence(self) -> bool:
        return self.confidence is not None and self.confidence < settings.confidence_cutoff


def _prompt(designation: str, non_qualifying: Tuple[str, ...]) -> str:
    cats = ", ".join(non_qualifying)
    return (
        "You classify a job title for an EDB RIS(C) R&D grant. A person QUALIFIES "
        "for gate G5 only if their role is a hands-on research/science/engineering "
        "(R&D) role. They do NOT qualify if the role falls in any of these "
        f"non-qualifying support categories: {cats}.\n\n"
        "Judge the title below. A managerial title can still qualify if the work is "
        "clearly hands-on technical R&D (e.g. 'Engineering Manager' leading "
        "developers), but a pure support/business role does not. If you cannot tell, "
        "set category to \"Uncertain\", qualifies to true (do not exclude on a guess), "
        "and a low confidence.\n\n"
        "Return JSON: {\"category\": \"<one category or 'Technical/R&D' or "
        "'Uncertain'>\", \"qualifies\": <true|false>, \"justification\": \"<one "
        "line>\", \"confidence\": <0..1>}.\n\n"
        f"TITLE: {designation!r}"
    )


def judge_designation(
    designation: str,
    deterministic_passed: bool,
    deterministic_reason: Optional[str] = None,
    *,
    client: Optional[LLMClient] = None,
    config: Config = settings,
) -> DesignationJudgement:
    """Judge one designation. LLM proposes; the gate result stays authoritative.

    With no endpoint (or a failed call) returns an offline judgement that echoes
    the deterministic outcome and reason, so callers get a uniform object either
    way and nothing is hidden (FR-14).
    """
    title = (designation or "").strip()
    use_client = client if client is not None else _safe_client(config)
    # Online exactly when a client exists and the config points at an endpoint
    # (mirrors AuditAssistant). Tests inject a client with an enabled config.
    online = use_client is not None and config.llm_enabled

    if online:
        res = use_client.call(_prompt(title, config.non_qualifying_designations),
                              schema=_JUDGE_SCHEMA)
        if res.ok and res.parsed:
            p = res.parsed
            return DesignationJudgement(
                designation=title,
                proposed_qualifies=bool(p.get("qualifies", deterministic_passed)),
                category=str(p.get("category") or "Uncertain"),
                justification=str(p.get("justification") or "").strip(),
                confidence=(res.confidence if res.confidence is not None
                            else p.get("confidence")),
                deterministic_passed=deterministic_passed,
                used_model=True,
                offline=False,
            )
        # model present but call failed -> fall through to the offline echo

    return DesignationJudgement(
        designation=title,
        proposed_qualifies=deterministic_passed,
        category="Technical/R&D" if deterministic_passed else "Non-qualifying",
        justification=(deterministic_reason or
                       "Deterministic G5 outcome (model not consulted)."),
        confidence=None,
        deterministic_passed=deterministic_passed,
        used_model=False,
        offline=not online,
    )


def judge_review_cases(
    result: Any,
    *,
    client: Optional[LLMClient] = None,
    config: Config = settings,
) -> dict:
    """Judge every employee whose G5 the deterministic layer flagged for review.

    Duck-types the pipeline result (no import of ``app``) per the layering rule.
    Returns ``{employee_id: DesignationJudgement}`` for the borderline cases only;
    clean passes/fails the gate already settled are not re-judged (FR-10: "clear
    passes/fails are pre-filled"). Cached calls make reruns identical (§9).
    """
    use_client = client if client is not None else _safe_client(config)
    out: dict = {}
    for e in getattr(result, "all_employees", ()):  # type: ignore[union-attr]
        g5 = next((ev for ev in e.gate_evaluations if ev.gate.value == "G5"), None)
        if g5 is None or not g5.needs_review:
            continue
        out[e.employee.id] = judge_designation(
            e.employee.designation,
            g5.passed,
            g5.reason,
            client=use_client,
            config=config,
        )
    return out


def _safe_client(config: Config) -> Optional[LLMClient]:
    try:
        return LLMClient(config)
    except Exception:  # never let model setup break the pipeline (FR-14)
        return None
