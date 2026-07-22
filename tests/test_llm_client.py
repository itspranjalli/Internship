"""Tests for edb_claim.llm.client + edb_claim.llm.cache (T15).

Covers the three required behaviours:
  (a) NO endpoint configured -> a call returns the graceful-unavailable result
      WITHOUT raising (CLAUDE.md: deterministic pipeline runs with no model).
  (b) cache miss then hit -> the hit replays an identical result (PRD section 9).
  (c) the cache key is stable across runs for identical inputs (no time/random).

A mock transport exercises the "model present" path with no network and no live
model (the Qwen endpoint is DEFERRED).

Runs under pytest (`.venv/bin/python -m pytest tests/test_llm_client.py -q`) OR
directly: `python tests/test_llm_client.py` (plain-assert harness at the bottom).
"""

import os
import sys
import tempfile
from dataclasses import replace

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from edb_claim.config import Config
from edb_claim.llm.cache import LLMCache, LLMRecord, cache_key
from edb_claim.llm.client import LLMClient, validate_against_schema


# --- fixtures (plain helpers; no pytest fixture needed) --------------------
_SCHEMA = {
    "type": "object",
    "required": ["basic_salary"],
    "properties": {"basic_salary": {"type": "number"}},
}


def _tmp_config(tmpdir, *, base_url=None, model=None):
    """A Config whose llm cache + db live under an isolated tmp dir."""
    return Config(
        llm_base_url=base_url,
        llm_model=model,
        db_path=os.path.join(tmpdir, "edb_claim.db"),
    )


class _MockTransport:
    """Records calls and returns a canned schema-valid payload."""

    def __init__(self, payload=None, confidence=0.91, reason="single salary line, clear print"):
        self.payload = payload or {"basic_salary": 9500.0}
        self.confidence = confidence
        self.reason = reason
        self.calls = 0

    def __call__(self, prompt, model, schema, temperature):
        self.calls += 1
        import json as _json

        return {
            "text": _json.dumps(self.payload),
            "confidence": self.confidence,
            "confidence_reason": self.reason,
        }


# --- (a) graceful degradation: NO endpoint ---------------------------------
def test_no_endpoint_returns_unavailable_without_raising():
    with tempfile.TemporaryDirectory() as d:
        cfg = _tmp_config(d)  # base_url=None -> stub mode
        assert cfg.llm_enabled is False
        client = LLMClient(cfg)
        res = client.call("extract salary", schema=_SCHEMA, source_ref={"file": "p.xlsx"})
        # Did not raise; returned a typed unavailable result.
        assert res.ok is False
        assert res.status == "unavailable"
        assert res.available is False
        assert res.parsed is None
        assert res.error == "no_endpoint"
        # FR-14: a plain-language reason is always carried, never discarded.
        assert res.confidence_reason and "not configured" in res.confidence_reason
        # FR-7: the source_ref is echoed back unchanged.
        assert res.source_ref == {"file": "p.xlsx"}


def test_no_endpoint_still_replays_cache():
    # Even with no live endpoint, a previously cached result must replay (section 9).
    with tempfile.TemporaryDirectory() as d:
        cfg = _tmp_config(d)
        key = cache_key("p", cfg.llm_model, _SCHEMA)
        cache = LLMCache(cfg.db_path.replace(".db", ".llm_cache.json"))
        cache.put(LLMRecord(key=key, model=cfg.llm_model, prompt="p",
                            raw_response='{"basic_salary": 1.0}', parsed={"basic_salary": 1.0},
                            confidence=0.5))
        client = LLMClient(cfg)
        res = client.call("p", schema=_SCHEMA)
        assert res.ok is True
        assert res.cache_hit is True
        assert res.parsed == {"basic_salary": 1.0}


# --- (b) cache miss then hit replays identically ---------------------------
def test_cache_miss_then_hit_is_identical():
    with tempfile.TemporaryDirectory() as d:
        cfg = _tmp_config(d, base_url="http://localhost:8000/v1", model="qwen-test")
        transport = _MockTransport({"basic_salary": 9500.0})
        client = LLMClient(cfg, transport=transport)

        first = client.call("extract", schema=_SCHEMA, source_ref={"file": "p.xlsx", "cell": "C5"})
        assert first.ok is True
        assert first.cache_hit is False
        assert transport.calls == 1
        assert first.parsed == {"basic_salary": 9500.0}
        assert first.confidence == 0.91

        # A fresh client over the same cache file -> hit, transport NOT called again.
        transport2 = _MockTransport({"basic_salary": -1.0})  # different payload to prove replay
        client2 = LLMClient(cfg, transport=transport2)
        second = client2.call("extract", schema=_SCHEMA, source_ref={"file": "p.xlsx", "cell": "C5"})
        assert second.cache_hit is True
        assert transport2.calls == 0
        # Identical replay -- not the second transport's payload.
        assert second.parsed == first.parsed
        assert second.confidence == first.confidence
        assert second.confidence_reason == first.confidence_reason


# --- (c) stable cache key across runs --------------------------------------
def test_cache_key_is_stable_and_provenance_free():
    k1 = cache_key("prompt X", "qwen", _SCHEMA)
    k2 = cache_key("prompt X", "qwen", dict(_SCHEMA))  # rebuilt schema dict
    assert k1 == k2  # stable across identical inputs (sorted-keys canonical JSON)

    # source_ref / confidence_hint are NOT key material: same key regardless.
    with tempfile.TemporaryDirectory() as d:
        cfg = _tmp_config(d, base_url="http://x/v1", model="qwen")
        t = _MockTransport()
        client = LLMClient(cfg, transport=t)
        client.call("prompt X", schema=_SCHEMA, source_ref={"file": "a"})
        # Second call, different source_ref -> still a cache hit on the same key.
        res = client.call("prompt X", schema=_SCHEMA, source_ref={"file": "b"})
        assert res.cache_hit is True
        assert t.calls == 1
        # but the CURRENT call's source_ref is echoed (FR-7), not the stored one.
        assert res.source_ref == {"file": "b"}

    # Changing any key component changes the key.
    assert cache_key("prompt Y", "qwen", _SCHEMA) != k1
    assert cache_key("prompt X", "other", _SCHEMA) != k1
    assert cache_key("prompt X", "qwen", None) != k1


# --- supporting behaviour: validation + retry + record shape ---------------
def test_schema_validation_rejects_bad_type():
    try:
        validate_against_schema({"basic_salary": "not a number"}, _SCHEMA)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for wrong field type")
    # bool must not satisfy a numeric field (bool is a subclass of int).
    try:
        validate_against_schema({"basic_salary": True}, _SCHEMA)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError: bool is not a number")
    # missing required field
    try:
        validate_against_schema({}, _SCHEMA)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for missing required field")


def test_invalid_output_retries_then_errors_without_raising():
    with tempfile.TemporaryDirectory() as d:
        cfg = _tmp_config(d, base_url="http://x/v1", model="qwen")

        def bad_transport(prompt, model, schema, temperature):
            return {"text": "not json at all"}

        client = LLMClient(cfg, transport=bad_transport, max_retries=2)
        res = client.call("p", schema=_SCHEMA)
        assert res.ok is False
        assert res.status == "error"
        assert res.error is not None
        assert "attempts" in (res.confidence_reason or "")


def test_record_to_row_maps_to_llm_log_shape():
    rec = LLMRecord(
        key="abc", model="qwen", prompt="p", raw_response='{"x":1}',
        parsed={"x": 1}, confidence=0.8, confidence_reason="ok",
        source_ref={"file": "p.xlsx", "cell": "C5"}, schema_name="salary",
        created_at="2026-06-15T00:00:00+00:00",
    )
    row = rec.to_row()
    # llm_log columns are flat; nested dicts become JSON TEXT.
    assert set(row) == {
        "key", "model", "prompt", "raw_response", "parsed", "confidence",
        "confidence_reason", "source_ref", "schema_name", "created_at",
    }
    assert row["parsed"] == '{"x": 1}'
    assert '"cell": "C5"' in row["source_ref"]


def test_confidence_hint_used_when_model_returns_none():
    with tempfile.TemporaryDirectory() as d:
        cfg = _tmp_config(d, base_url="http://x/v1", model="qwen")

        def no_conf_transport(prompt, model, schema, temperature):
            import json as _json
            return {"text": _json.dumps({"basic_salary": 5000.0})}  # no confidence key

        client = LLMClient(cfg, transport=no_conf_transport)
        res = client.call("p", schema=_SCHEMA, confidence_hint=0.42)
        assert res.confidence == 0.42


# --- Plain-assert runner (no pytest required) ------------------------------
def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} llm client/cache tests passed.")


if __name__ == "__main__":
    _run_all()
