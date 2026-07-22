"""Round-trip tests for the FR-13 persistence layer (T22).

Creates a temp-file DB (NOT the real config.db_path), initialises the schema,
writes a sample Employee + PersonMonth + calc results + EvidenceRef + Verdict +
GateResult + llm_log via the write-through API, reads them back via the
exact-SQL retrieval API, and asserts round-trip equality.

Runs under pytest OR directly: `.venv/bin/python tests/test_db_store.py`.
"""

import os
import sys
import tempfile

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from edb_claim.db import schema, store
from edb_claim.domain.models import (
    CalcMethod,
    Citizenship,
    Employee,
    EvidenceRef,
    GateCode,
    GateResult,
    HireType,
    MethodAResult,
    MethodBResult,
    MonthlyBreakdownA,
    MonthlyBreakdownB,
    PersonMonth,
    Verdict,
    VerdictStatus,
)


def _sample_employee():
    return Employee(
        id="E1",
        name="Tan Wei Ming",
        entity="ST Engineering IHQ Pte Ltd (GEC)",
        citizenship=Citizenship.CITIZEN,
        ecmf_validated=True,
        no_other_grant=True,
        designation="AI Research Engineer",
        hire_type=HireType.UPSKILLED,
        normalized_name="ming tan wei",
    )


def test_schema_init_reports_vec_backend():
    with tempfile.TemporaryDirectory() as d:
        info = schema.init_db(os.path.join(d, "t.db"))
        assert info.vec_backend in ("vec0", "placeholder")
        assert info.embedding_dim == schema.DEFAULT_EMBEDDING_DIM
        # idempotent: second init must not raise
        schema.init_db(os.path.join(d, "t.db"))


def test_round_trip():
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "roundtrip.db")
        info = schema.init_db(db_path)
        conn = store.connect(db_path)
        try:
            emp = _sample_employee()
            store.write_employee(conn, emp)

            pm = PersonMonth(
                employee_id="E1", year=2026, month=3,
                basic_salary=9500.0, hours=123.4,
            )
            store.write_person_month(conn, pm)

            a = MethodAResult(
                employee_id="E1",
                qualifying_cost_total=24369.565217,
                support_rate=0.30,
                claim_amount=7310.869565,
                monthly=(
                    MonthlyBreakdownA(2026, 3, 9500.0, 0.565217, 1.0, 5369.565217),
                ),
            )
            b = MethodBResult(
                employee_id="E1",
                qualifying_cost_total=24000.0,
                support_rate=0.30,
                claim_amount=7200.0,
                new_hire=True,
                monthly=(
                    MonthlyBreakdownB(2026, 3, 9500.0, 176.0, 176.0, 1.0, 9500.0),
                ),
            )
            store.write_calc_result(conn, a)
            store.write_calc_result(conn, b)

            ref = EvidenceRef(
                file="payslip_E1_2026-03.xlsx", sheet="Sheet1",
                cell_or_row="C7", label="basic_salary",
            )
            ref_id = store.write_evidence_ref(conn, "E1", "E1:2026-03:basic_salary", ref)

            gr = GateResult(
                gate=GateCode.G4, passed=True,
                reason="basic salary 9500 >= floor 5000",
            )
            store.write_gate_result(conn, "E1", gr, ref_id=ref_id)

            v = Verdict(
                employee_id="E1", status=VerdictStatus.QUALIFIES,
                failed_gates=(), reasons=(),
            )
            store.write_verdict(conn, v)

            store.write_llm_log(
                conn, cache_key="abc123", prompt="extract basic salary",
                created_at="2026-06-15T00:00:00Z", employee_id="E1",
                purpose="extract", model="qwen", raw_response="{...}",
                parsed='{"basic_salary": 9500}', confidence=0.92,
                run_id="run-001",
            )
            conn.commit()

            # --- read back via exact-SQL retrieval ---
            r_emp = store.get_employee(conn, "E1")
            assert r_emp["name"] == "Tan Wei Ming"
            assert r_emp["entity_id"] == emp.entity
            assert r_emp["citizenship"] == "Citizen"
            assert r_emp["ecmf_validated"] == 1
            assert r_emp["hire_type"] == "Upskilled"

            r_pm = store.get_person_month(conn, "E1", 2026, 3)
            assert r_pm["basic_salary"] == 9500.0
            assert r_pm["hours"] == 123.4

            r_a = store.get_calc(conn, "E1", "A")
            assert r_a["claim_amount"] == a.claim_amount
            assert r_a["new_hire"] is None
            assert len(r_a["monthly"]) == 1
            assert r_a["monthly"][0]["qualifying_cost"] == 5369.565217

            r_b = store.get_calc(conn, "E1", CalcMethod.B)
            assert r_b["new_hire"] == 1
            assert r_b["claim_amount"] == 7200.0

            r_ev = store.get_evidence(conn, "E1:2026-03:basic_salary")
            assert len(r_ev) == 1
            assert r_ev[0]["file"] == "payslip_E1_2026-03.xlsx"
            assert r_ev[0]["cell_or_row"] == "C7"
            assert r_ev[0]["label"] == "basic_salary"

            r_gr = store.get_gate_results(conn, "E1")
            assert len(r_gr) == 1
            assert r_gr[0]["gate"] == "G4"
            assert r_gr[0]["passed"] == 1
            assert r_gr[0]["ref_id"] == ref_id

            verdicts = store.list_verdicts(conn)
            assert len(verdicts) == 1
            assert verdicts[0]["status"] == "QUALIFIES"
            assert verdicts[0]["failed_gates"] == []

            by_entity = store.list_verdicts(conn, entity=emp.entity)
            assert len(by_entity) == 1
            assert store.list_verdicts(conn, entity="No Such Entity") == []

            single = store.get_verdict(conn, "E1")
            assert single["status"] == "QUALIFIES"

            r_log = store.get_llm_log(conn, "abc123")
            assert r_log["prompt"] == "extract basic salary"
            assert r_log["created_at"] == "2026-06-15T00:00:00Z"
            assert r_log["confidence"] == 0.92
            assert r_log["run_id"] == "run-001"
        finally:
            conn.close()


def test_nric_and_identity_resolution():
    """Employee NRIC persists and resolves (by id, NRIC, and an extra alias)."""
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "identity.db")
        schema.init_db(db_path)
        conn = store.connect(db_path)
        try:
            emp = Employee(
                id="E1", name="Tan Wei Ming",
                entity="ST Engineering IHQ Pte Ltd (GEC)",
                citizenship=Citizenship.CITIZEN, ecmf_validated=True,
                no_other_grant=True, designation="AI Research Engineer",
                hire_type=HireType.UPSKILLED, nric="S1234567A",
            )
            store.write_employee(conn, emp)
            store.add_identifier(conn, "payroll_id", "PR-0007", "E1")
            conn.commit()

            assert store.get_employee(conn, "E1")["nric"] == "S1234567A"
            # by employee_id, by NRIC (case/space-insensitive), by payroll alias
            assert store.resolve_employee(conn, "E1") == "E1"
            assert store.resolve_employee(conn, " s1234567a ") == "E1"
            assert store.resolve_employee(conn, "PR-0007") == "E1"
            assert store.resolve_employee(conn, "nobody") is None
        finally:
            conn.close()


def test_document_blob_round_trip():
    """Store a per-person doc + a shared workbook, list and fetch them back."""
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "docs.db")
        schema.init_db(db_path)
        conn = store.connect(db_path)
        try:
            for i in ("E1", "E2"):
                store.write_employee(conn, Employee(
                    id=i, name=f"Person {i}", entity="GEC",
                    citizenship=Citizenship.CITIZEN, ecmf_validated=True,
                    no_other_grant=True, designation="RSE",
                    hire_type=HireType.NEW_HIRE,
                ))

            pdf = b"%PDF-1.4 fake payslip bytes"
            did = store.store_document(
                conn, "E1", file="payslip_E1_2026-03.pdf", content=pdf,
                doc_type="payslip", month="2026-03", mime_type="application/pdf",
                orig_filename="March Payslip.pdf", uploaded_at="2026-07-20T00:00:00Z",
            )
            # a shared workbook linked to BOTH employees = ONE document row
            wb = b"PK fake xlsx bytes"
            wb_id = store.store_document(conn, "E1", file="timesheet.xlsx", content=wb,
                                         doc_type="timesheet")
            store.add_doc_link(conn, wb_id, "E2")
            conn.commit()

            e1_docs = store.documents_of(conn, "E1")
            assert {r["doc_type"] for r in e1_docs} == {"payslip", "timesheet"}
            payslip = [r for r in e1_docs if r["doc_type"] == "payslip"][0]
            assert payslip["byte_size"] == len(pdf)
            assert payslip["month"] == "2026-03"
            assert payslip["orig_filename"] == "March Payslip.pdf"

            # filters
            assert len(store.documents_of(conn, "E1", doc_type="payslip")) == 1
            assert len(store.documents_of(conn, "E1", month="2026-03")) == 1
            # shared doc reaches E2 without a duplicate document row
            assert [r["doc_id"] for r in store.documents_of(conn, "E2")] == [wb_id]
            assert conn.execute("SELECT COUNT(*) FROM document").fetchone()[0] == 2

            # fetch the actual bytes back
            content, mime, fname = store.fetch_blob(conn, did)
            assert content == pdf
            assert mime == "application/pdf"
            assert fname == "March Payslip.pdf"
            assert store.fetch_blob(conn, "no-such-doc") is None

            # idempotent: re-store identical bytes under a derived id -> no dup
            again = store.store_document(conn, "E1", file="payslip_E1_2026-03.pdf",
                                         content=pdf, doc_type="payslip", month="2026-03")
            assert again == did
            assert conn.execute("SELECT COUNT(*) FROM doc_blob").fetchone()[0] == 2
        finally:
            conn.close()


def test_upsert_is_idempotent():
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "upsert.db")
        schema.init_db(db_path)
        conn = store.connect(db_path)
        try:
            emp = _sample_employee()
            store.write_employee(conn, emp)
            store.write_employee(conn, emp)  # second write must not duplicate/raise
            conn.commit()
            n = conn.execute("SELECT COUNT(*) FROM employee").fetchone()[0]
            assert n == 1
        finally:
            conn.close()


if __name__ == "__main__":
    test_schema_init_reports_vec_backend()
    test_round_trip()
    test_nric_and_identity_resolution()
    test_document_blob_round_trip()
    test_upsert_is_idempotent()
    print("all T22 store tests passed")
