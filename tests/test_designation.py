"""Tests for FR-10 LLM designation judging (edb_claim.llm.designation).

Pins the hard boundary: the model proposes, the deterministic gate disposes. With
no endpoint the judgement echoes the gate verbatim (offline, nothing discarded);
with an injected model it carries the proposal + confidence and flags model/gate
disagreement. judge_review_cases only touches the borderline G5 cases.
"""

import dataclasses
import os
import sys
import tempfile

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from edb_claim.app.pipeline import run_pipeline
from edb_claim.config import settings
from edb_claim.llm.cache import LLMCache
from edb_claim.llm.client import LLMClient
from edb_claim.llm.designation import judge_designation, judge_review_cases

_SAMPLE = os.path.join(_REPO_ROOT, "sample_data")


def _enabled_client(mock):
    cfg = dataclasses.replace(settings, llm_base_url="http://localhost:9/v1", llm_model="qwen")
    cache = LLMCache(os.path.join(tempfile.mkdtemp(), "cache.json"))
    return cfg, LLMClient(cfg, cache=cache, transport=mock)


def _result():
    return run_pipeline(
        [os.path.join(_SAMPLE, "internal_ANS.xlsx"), os.path.join(_SAMPLE, "internal_DSG.xlsx")],
        os.path.join(_SAMPLE, "rse_list.xlsx"),
        os.path.join(_SAMPLE, "payroll.xlsx"),
    )


_OFFLINE = dataclasses.replace(settings, llm_base_url=None, llm_model=None)


def test_offline_echoes_deterministic_outcome():
    j = judge_designation("Engineering Operations Manager", True, "borderline -> review",
                          config=_OFFLINE)
    assert j.used_model is False and j.offline is True
    assert j.proposed_qualifies is True          # echoes the gate
    assert j.agrees_with_gate is True
    assert "borderline" in j.justification


def test_model_proposal_can_disagree_with_gate():
    def mock(prompt, model, schema, temp):
        return {"text": '{"category": "Sales", "qualifies": false, '
                        '"justification": "Reads as a sales role.", "confidence": 0.91}'}
    cfg, client = _enabled_client(mock)
    # deterministic provisionally passed (True); model says non-qualifying (False)
    j = judge_designation("Sales Operations Lead", True, "ambiguous", client=client, config=cfg)
    assert j.used_model is True
    assert j.proposed_qualifies is False
    assert j.agrees_with_gate is False           # surfaced to HR
    assert j.category == "Sales" and j.confidence == 0.91


def test_confidence_hint_low_flag():
    def mock(prompt, model, schema, temp):
        return {"text": '{"category": "Uncertain", "qualifies": true, '
                        '"justification": "Cannot tell.", "confidence": 0.4}'}
    cfg, client = _enabled_client(mock)
    j = judge_designation("Operations Lead", True, "ambiguous", client=client, config=cfg)
    assert j.confidence == 0.4
    assert j.low_confidence is True


def test_judge_review_cases_only_touches_borderline():
    """Only employees whose G5 was flagged needs_review get a model judgement."""
    def mock(prompt, model, schema, temp):
        return {"text": '{"category": "Technical/R&D", "qualifies": true, '
                        '"justification": "Hands-on engineering.", "confidence": 0.8}'}
    cfg, client = _enabled_client(mock)
    res = _result()
    judged = judge_review_cases(res, client=client, config=cfg)
    review_ids = {e.employee.id for e in res.all_employees
                  if any(ev.gate.value == "G5" and ev.needs_review for ev in e.gate_evaluations)}
    assert set(judged) == review_ids
    for j in judged.values():
        assert j.used_model is True


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"ok   {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1; print(f"FAIL {fn.__name__}: {exc}")
    sys.exit(1 if failed else 0)
