"""FR-11 — LLM cross-document reconciliation (PLAN.md T18).

The pipeline joins the Time Sheet to the ECMF RSE list (the G1/G2 authority) and
the payroll by **exact Employee ID**. When the same person appears under a name
variant ("Tan Wei Ming" vs "WEI MING TAN") or a differing/typo'd ID, that exact
join silently misses — and a missed RSE join means G1/G2 cannot be evaluated, so
the person is wrongly excluded. This module catches those near-misses.

Deterministic auto-accept rule (FR-11, ASSUMED, CLAUDE.md determinism):

  * **Exact Employee-ID match** across documents -> auto-accepted, no model.
  * **Normalized-name-only / fuzzy / typo match** (different or absent ID) ->
    routed to an HR confirmation queue, with the LLM proposing whether it is the
    same person, a one-line reason grounded in the two records, and a confidence.
  * **No id and no name match** -> reported as unmatched (never silently dropped).

HARD BOUNDARY (CLAUDE.md / PRD §7): the LLM only proposes a *match*; it computes
no figure and does not auto-merge records. HR confirms ambiguous matches in the
UI (FR-14). The accept/queue decision is deterministic and the LLM call is cached,
so reruns are identical (§9). Degrades gracefully with the endpoint down: name
matches are still surfaced for HR, just without a model-written rationale.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from edb_claim.config import Config, settings
from edb_claim.llm.client import LLMClient

_MATCH_SCHEMA = {
    "type": "object",
    "required": ["same_person", "confidence", "reason"],
    "properties": {
        "same_person": {"type": "boolean"},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
}


@dataclass(frozen=True)
class Party:
    """One identity as it appears in one source document."""

    source: str   # "timesheet" | "rse_list" | "payroll"
    id: str
    name: str


@dataclass(frozen=True)
class MatchProposal:
    """A proposed cross-document identity link (FR-11/FR-14).

    ``auto_accepted`` is the deterministic exact-ID case (no model, certain).
    Otherwise it is a name/fuzzy candidate routed to HR: ``needs_confirmation`` is
    True and ``same_person`` carries the model's proposal (defaulting to the
    deterministic name-set match when the model is offline).
    """

    timesheet_id: str
    timesheet_name: str
    candidate_source: str
    candidate_id: str
    candidate_name: str
    match_kind: str               # "exact_id" | "name_variant" | "fuzzy"
    auto_accepted: bool
    same_person: bool
    needs_confirmation: bool
    confidence: Optional[float]
    reason: str
    used_model: bool = False
    offline: bool = False


def _norm_name(name: str) -> str:
    """Lower-case, strip punctuation, collapse spaces (order-preserving)."""
    return " ".join(re.findall(r"[a-z0-9]+", (name or "").lower()))


def _name_key(name: str) -> frozenset:
    """Order-independent token set so 'Tan Wei Ming' == 'WEI MING TAN'."""
    return frozenset(_norm_name(name).split())


def _levenshtein_le1(a: str, b: str) -> bool:
    """True if ``a`` and ``b`` differ by at most one edit (cheap typo check)."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    # find first differing position
    i = 0
    while i < min(la, lb) and a[i] == b[i]:
        i += 1
    if la == lb:                       # substitution
        return a[i + 1:] == b[i + 1:]
    if la < lb:                        # insertion into a
        return a[i:] == b[i + 1:]
    return a[i + 1:] == b[i:]           # deletion from a


def _prompt(ts: Party, cand: Party) -> str:
    return (
        "Two records may refer to the same employee across HR documents for an EDB "
        "grant claim. Decide if they are the SAME person. Name order may differ "
        "('Tan Wei Ming' vs 'WEI MING TAN'), and IDs may differ or be missing.\n\n"
        f"RECORD A (timesheet): id={ts.id!r}, name={ts.name!r}\n"
        f"RECORD B ({cand.source}): id={cand.id!r}, name={cand.name!r}\n\n"
        "Return JSON: {\"same_person\": <true|false>, \"confidence\": <0..1>, "
        "\"reason\": \"<one line grounded in the names/ids above>\"}."
    )


def reconcile_rosters(
    timesheet: Sequence[Party],
    others: Sequence[Party],
    *,
    client: Optional[LLMClient] = None,
    config: Config = settings,
) -> List[MatchProposal]:
    """Reconcile each timesheet party against the other-source roster.

    Returns one :class:`MatchProposal` per timesheet party that did NOT have an
    exact-ID match but does have a name/fuzzy candidate (the HR queue), plus the
    exact-ID auto-accepts (so the UI can show coverage). Parties with a clean
    exact-ID match are returned as ``auto_accepted`` proposals; parties with no
    candidate at all are omitted (the gates already report the missing RSE join).
    """
    use_client = client if client is not None else _safe_client(config)
    online = use_client is not None and config.llm_enabled

    by_id: Dict[str, Party] = {p.id: p for p in others if p.id}
    proposals: List[MatchProposal] = []

    for ts in timesheet:
        # 1) exact-ID -> deterministic auto-accept, no model.
        if ts.id and ts.id in by_id:
            cand = by_id[ts.id]
            proposals.append(MatchProposal(
                timesheet_id=ts.id, timesheet_name=ts.name,
                candidate_source=cand.source, candidate_id=cand.id,
                candidate_name=cand.name, match_kind="exact_id",
                auto_accepted=True, same_person=True, needs_confirmation=False,
                confidence=1.0,
                reason=f"Exact Employee-ID match ({ts.id}).",
            ))
            continue

        # 2) no exact-ID: look for a name-variant or single-typo candidate.
        ts_key = _name_key(ts.name)
        cand: Optional[Party] = None
        kind = ""
        for o in others:
            if _name_key(o.name) == ts_key and ts_key:
                cand, kind = o, "name_variant"
                break
        if cand is None:
            ts_norm = _norm_name(ts.name)
            for o in others:
                if ts_norm and _levenshtein_le1(ts_norm, _norm_name(o.name)):
                    cand, kind = o, "fuzzy"
                    break
        if cand is None:
            continue  # no candidate; missing-RSE handled by gates, not invented here

        # 3) ambiguous -> HR confirmation queue, with an LLM-proposed call.
        same, conf, reason, used_model = True, None, "", False
        if online and use_client is not None:
            res = use_client.call(_prompt(ts, cand), schema=_MATCH_SCHEMA)
            if res.ok and res.parsed:
                same = bool(res.parsed.get("same_person", True))
                conf = (res.confidence if res.confidence is not None
                        else res.parsed.get("confidence"))
                reason = str(res.parsed.get("reason") or "").strip()
                used_model = True
        if not used_model:
            reason = (f"Names match ignoring order/case ({ts.name!r} ~ "
                      f"{cand.name!r}) but IDs differ ({ts.id!r} vs {cand.id!r})."
                      if kind == "name_variant" else
                      f"Names are within one edit ({ts.name!r} ~ {cand.name!r}); "
                      f"likely a typo.")

        proposals.append(MatchProposal(
            timesheet_id=ts.id, timesheet_name=ts.name,
            candidate_source=cand.source, candidate_id=cand.id,
            candidate_name=cand.name, match_kind=kind,
            auto_accepted=False, same_person=same, needs_confirmation=True,
            confidence=conf, reason=reason,
            used_model=used_model, offline=not online,
        ))
    return proposals


def reconcile_result(
    result: Any,
    rse_records: Sequence[Any] = (),
    *,
    client: Optional[LLMClient] = None,
    config: Config = settings,
) -> List[MatchProposal]:
    """Reconcile the pipeline's timesheet roster against the ECMF RSE list.

    Duck-types the pipeline result (employees with ``.id``/``.name``) and the RSE
    records (``.employee_id``/``.name``) so the layering rule holds (no import of
    ``app``/``ingest``). The RSE list is the G1/G2 authority, so it is the
    reconciliation target that matters; a missed join there is what wrongly
    excludes a person.
    """
    ts = [Party("timesheet", e.employee.id, e.employee.name)
          for e in getattr(result, "all_employees", ())]
    others = [Party("rse_list", getattr(r, "employee_id", ""), getattr(r, "name", ""))
              for r in rse_records]
    return reconcile_rosters(ts, others, client=client, config=config)


def _safe_client(config: Config) -> Optional[LLMClient]:
    try:
        return LLMClient(config)
    except Exception:
        return None
