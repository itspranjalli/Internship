"""Tests for the grounded audit Q&A assistant (FR-12) — edb_claim.llm.qa.

Verifies the two-path routing: structured questions (claim, totals, who-is-excluded,
"fetch the evidence for X") are answered from real pipeline rows with citations and
no model; scheme questions retrieve from the knowledge base and, when a model is
present (injected mock + enabled config), are phrased by the model — otherwise they
degrade gracefully offline. Also pins the hard boundary: a figure in an answer
matches the pipeline figure to the cent (never invented).
"""

import dataclasses
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from edb_claim.app.pipeline import run_pipeline
from edb_claim.config import settings
from edb_claim.llm.client import LLMClient
from edb_claim.llm.qa import AuditAssistant

_SAMPLE = os.path.join(_REPO_ROOT, "sample_data")


def _result():
    return run_pipeline(
        [os.path.join(_SAMPLE, "internal_ANS.xlsx"), os.path.join(_SAMPLE, "internal_DSG.xlsx")],
        os.path.join(_SAMPLE, "rse_list.xlsx"),
        os.path.join(_SAMPLE, "payroll.xlsx"),
    )


def test_total_claim_is_grounded_to_the_cent():
    res = _result()
    a = AuditAssistant().answer("What is the total claim?", res)
    assert a.mode == "data" and a.grounded
    assert f"{res.total_claim_a:,.2f}" in a.text


def test_employee_claim_lookup_uses_real_figure():
    res = _result()
    a = AuditAssistant().answer("What is the claim for ANS-002?", res)
    emp = next(e for e in res.all_employees if e.employee.id == "ANS-002")
    assert f"{emp.method_a.claim_amount:,.2f}" in a.text


def test_excluded_reason_is_reported():
    res = _result()
    a = AuditAssistant().answer("Why is Arjun Mehta not eligible?", res)
    assert a.mode == "data"
    assert "G1" in a.text or "local" in a.text.lower() or "foreigner" in a.text.lower()


def test_fetch_evidence_returns_citations_and_documents():
    res = _result()
    a = AuditAssistant().answer("fetch the evidence for ANS-001", res)
    assert a.mode == "evidence"
    assert a.citations, "expected source citations"
    assert all("file" in c and "cell" in c for c in a.citations)


def test_counts_route_not_confused_by_word_counts():
    """'what salary counts' must NOT hit the roster branch (regression)."""
    res = _result()
    a = AuditAssistant().answer("What salary counts towards the claim?", res)
    assert a.mode == "scheme"


def test_scheme_question_offline_returns_grounded_fact():
    res = _result()
    a = AuditAssistant().answer("What is the support rate?", res)
    assert a.mode == "scheme" and a.grounded
    assert a.offline is (not settings.llm_enabled)
    assert "support rate" in a.text.lower()


def test_scheme_question_uses_model_when_enabled():
    """With an enabled config + injected transport, the model phrases the answer."""
    def mock(prompt, model, schema, temp):
        return {"text": '{"answer": "Model-phrased answer grounded in context."}',
                "confidence": 0.88}

    import tempfile
    from edb_claim.llm.cache import LLMCache

    cfg = dataclasses.replace(settings, llm_base_url="http://localhost:9/v1", llm_model="qwen")
    # isolated cache so a persisted reply from another run can't replay over the mock
    cache = LLMCache(os.path.join(tempfile.mkdtemp(), "cache.json"))
    client = LLMClient(cfg, cache=cache, transport=mock)
    a = AuditAssistant(client=client, config=cfg).answer("Explain the support rate", _result())
    assert a.used_model is True
    assert a.text == "Model-phrased answer grounded in context."
    assert a.confidence == 0.88


def test_works_with_no_result_for_scheme_questions():
    a = AuditAssistant().answer("How is the claim calculated?", None)
    assert a.mode == "scheme" and a.text


# --- FR-13 RAG: fetch a record from the persisted store (no live result) ----
def _persisted_db():
    """Run the pipeline, persist it, return (db_path, result)."""
    import tempfile
    from edb_claim.db.schema import init_db
    from edb_claim.db.store import connect, persist_result

    res = _result()
    dbp = os.path.join(tempfile.mkdtemp(), "edb_claim.db")
    init_db(dbp)
    conn = connect(dbp)
    persist_result(conn, res)
    conn.close()
    return dbp, res


def test_record_fetched_from_store_when_no_live_result():
    """The chatbot retrieves a person's record by exact-SQL from the store,
    grounded to the cent, even though no in-memory result is passed (RAG)."""
    dbp, res = _persisted_db()
    emp = next(e for e in res.all_employees if e.employee.id == "ANS-001")
    cfg = dataclasses.replace(settings, db_path=dbp)
    a = AuditAssistant(config=cfg).answer("What is the claim for ANS-001?", result=None)
    assert a.mode == "data" and a.grounded
    assert f"{emp.method_a.claim_amount:,.2f}" in a.text   # figure from the stored row
    assert "saved records" in a.text


def test_evidence_fetched_from_store_has_unique_citations():
    dbp, _ = _persisted_db()
    cfg = dataclasses.replace(settings, db_path=dbp)
    a = AuditAssistant(config=cfg).answer("fetch the evidence for ANS-001", result=None)
    assert a.mode == "evidence" and a.citations
    keys = [(c["file"], c["cell"]) for c in a.citations]
    assert len(keys) == len(set(keys)), "citations must be de-duplicated"


def test_unknown_person_not_in_store_falls_back_to_scheme():
    """'if any' — an unknown name yields no record, so no figures are invented."""
    dbp, _ = _persisted_db()
    cfg = dataclasses.replace(settings, db_path=dbp)
    a = AuditAssistant(config=cfg).answer("claim for Zzz Nonexistent Person", result=None)
    assert a.mode != "data"  # no fabricated record


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"ok   {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    sys.exit(1 if failed else 0)
