"""Tests for FR-11 LLM cross-document reconciliation (edb_claim.llm.reconcile).

Pins the deterministic auto-accept rule (exact-ID = certain, no model) and the
HR-queue rule (name-variant / typo = model-proposed, needs confirmation), plus
graceful offline behaviour. The model proposes a match; it never auto-merges.
"""

import dataclasses
import os
import sys
import tempfile

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from edb_claim.config import settings
from edb_claim.llm.cache import LLMCache
from edb_claim.llm.client import LLMClient
from edb_claim.llm.reconcile import Party, reconcile_rosters, _levenshtein_le1, _name_key


def _enabled_client(mock):
    cfg = dataclasses.replace(settings, llm_base_url="http://localhost:9/v1", llm_model="qwen")
    cache = LLMCache(os.path.join(tempfile.mkdtemp(), "cache.json"))
    return cfg, LLMClient(cfg, cache=cache, transport=mock)


def test_exact_id_auto_accepts_without_model():
    ts = [Party("timesheet", "ANS-001", "Lim Hua")]
    others = [Party("rse_list", "ANS-001", "LIM HUA")]
    [m] = reconcile_rosters(ts, others)            # no client -> offline
    assert m.match_kind == "exact_id"
    assert m.auto_accepted is True and m.needs_confirmation is False
    assert m.same_person is True and m.confidence == 1.0
    assert m.used_model is False                   # determinism, no call


def test_name_variant_routes_to_hr_queue_with_model():
    def mock(prompt, model, schema, temp):
        return {"text": '{"same_person": true, "confidence": 0.93, '
                        '"reason": "Same tokens, reordered."}'}
    cfg, client = _enabled_client(mock)
    ts = [Party("timesheet", "TS-9", "Tan Wei Ming")]
    others = [Party("rse_list", "RSE-7", "WEI MING TAN")]
    [m] = reconcile_rosters(ts, others, client=client, config=cfg)
    assert m.match_kind == "name_variant"
    assert m.auto_accepted is False and m.needs_confirmation is True
    assert m.used_model is True and m.same_person is True and m.confidence == 0.93


def test_name_variant_offline_still_surfaced():
    ts = [Party("timesheet", "TS-9", "Tan Wei Ming")]
    others = [Party("rse_list", "RSE-7", "WEI MING TAN")]
    [m] = reconcile_rosters(ts, others)            # offline
    assert m.needs_confirmation is True and m.used_model is False
    assert "match" in m.reason.lower()


def test_typo_match_is_fuzzy():
    ts = [Party("timesheet", "TS-1", "Rajesh Kumar")]
    others = [Party("rse_list", "RSE-1", "Rajash Kumar")]   # one substitution
    [m] = reconcile_rosters(ts, others)
    assert m.match_kind == "fuzzy" and m.needs_confirmation is True


def test_no_candidate_is_omitted():
    ts = [Party("timesheet", "TS-1", "Completely Different")]
    others = [Party("rse_list", "RSE-1", "Nobody Here")]
    assert reconcile_rosters(ts, others) == []


def test_levenshtein_and_name_key():
    assert _levenshtein_le1("kumar", "kumer") is True      # substitution
    assert _levenshtein_le1("kumar", "kumars") is True     # insertion
    assert _levenshtein_le1("kumar", "kmr") is False       # >1 edit
    assert _name_key("Tan Wei Ming") == _name_key("WEI MING TAN")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"ok   {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1; print(f"FAIL {fn.__name__}: {exc}")
    sys.exit(1 if failed else 0)
