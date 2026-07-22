"""Tests for FR-9 LLM document extraction (edb_claim.llm.extract).

Pins: extraction is skipped (returns None/[]) with no endpoint; with an injected
model it parses the fixed schema and keeps the excluded components; the cross-check
flags an extracted basic that disagrees with the deterministic figure. The LLM
proposes — the deterministic basic remains the figure of record.
"""

import dataclasses
import os
import sys
import tempfile
from types import SimpleNamespace

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from edb_claim.config import settings
from edb_claim.llm.cache import LLMCache
from edb_claim.llm.client import LLMClient
from edb_claim.llm.extract import cross_check, extract_row


def _enabled_client(mock):
    cfg = dataclasses.replace(settings, llm_base_url="http://localhost:9/v1", llm_model="qwen")
    cache = LLMCache(os.path.join(tempfile.mkdtemp(), "cache.json"))
    return cfg, LLMClient(cfg, cache=cache, transport=mock)


_PAYLOAD = ('{"employee_id": "ANS-001", "month": "3", "basic_salary": 9500, '
            '"excluded_components": [{"name": "Allowances", "amount": 800}, '
            '{"name": "CPF (Employer)", "amount": 1615}], '
            '"payment_reference": "PAY-3", "confidence": 0.97, '
            '"confidence_reason": "All fields clear."}')


def test_extract_skipped_when_offline():
    assert extract_row({"Basic Salary": 9500}) is None


def test_extract_parses_schema_and_excludes():
    cfg, client = _enabled_client(lambda *a: {"text": _PAYLOAD})
    ex = extract_row({"Employee ID": "ANS-001", "Basic Salary": 9500}, client=client, config=cfg)
    assert ex.basic_salary == 9500.0 and ex.employee_id == "ANS-001"
    assert {c.name for c in ex.excluded} == {"Allowances", "CPF (Employer)"}
    assert ex.payment_reference == "PAY-3"
    assert ex.low_confidence(cfg) is False


def test_cross_check_agrees_with_deterministic():
    cfg, client = _enabled_client(lambda *a: {"text": _PAYLOAD})
    ex = extract_row({"Employee ID": "ANS-001"}, client=client, config=cfg)
    det = (SimpleNamespace(employee_id="ANS-001", year=2026, month=3, basic_salary=9500.0),)
    [chk] = cross_check([ex], det, config=cfg)
    assert chk.agrees is True and chk.deterministic_basic == 9500.0


def test_cross_check_flags_disagreement():
    cfg, client = _enabled_client(lambda *a: {"text": _PAYLOAD})  # extracted 9500
    ex = extract_row({"Employee ID": "ANS-001"}, client=client, config=cfg)
    det = (SimpleNamespace(employee_id="ANS-001", year=2026, month=3, basic_salary=8800.0),)
    [chk] = cross_check([ex], det, config=cfg)
    assert chk.agrees is False
    assert "differs" in chk.detail


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"ok   {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1; print(f"FAIL {fn.__name__}: {exc}")
    sys.exit(1 if failed else 0)
