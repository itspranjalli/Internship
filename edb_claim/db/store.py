"""FR-13 write-through + exact-SQL retrieval over the persistence store.

This module is the only sanctioned door between the domain objects
(:mod:`edb_claim.domain.models`) and the SQLite schema (:mod:`.schema`). It has
two jobs:

  1. **Write-through** -- persist domain value objects (Employee, PersonMonth,
     GateResult, Verdict, MethodAResult, MethodBResult, EvidenceRef) into the
     relational core. Writes are UPSERTs so a rerun of the same pipeline
     overwrites cleanly (idempotent / deterministic, PRD §9).

  2. **Exact-SQL retrieval** -- the **numeric** path for FR-12: numbers are read
     back by precise key lookup on the structured tables, *never* by vector
     similarity (PRD FR-13 "two retrieval paths, audit-safety"). All queries use
     a stable ``ORDER BY`` so identical inputs give identical row order.

Determinism rules honoured (PRD §9, task brief):
  * **No ``now()`` / random** is generated here. Any timestamp/run id a row
    needs (``llm_log.created_at``, ``run_id``) is *passed in* by the caller --
    the run manifest owns time.
  * JSON columns (verdict gates/reasons, calc monthly breakdown) are serialised
    with ``sort_keys=True`` so the stored bytes are stable.

llm_log / T15 compatibility: T15 (LLM client + cache) is **not yet implemented**
(no ``edb_claim/llm/cache.py`` at the time of writing). The ``llm_log`` columns
here are the canonical cache record shape derived from PLAN.md §1
(``cache.py: hash(prompt+model+schema) -> persisted prompt/raw/ref (= llm_log)``)
and PRD FR-13/FR-14. :func:`write_llm_log` is the contract T15 must populate;
its ``cache_key`` is the ``hash(prompt+model+schema)`` cache key.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import asdict
from typing import Optional, Sequence, Tuple

from ..domain.models import (
    CalcMethod,
    Employee,
    EvidenceRef,
    GateResult,
    MethodAResult,
    MethodBResult,
    PersonMonth,
    Verdict,
)
from .schema import connect, init_db

__all__ = [
    "connect",
    "init_db",
    # write-through
    "upsert_entity",
    "write_employee",
    "write_person_month",
    "write_gate_result",
    "write_verdict",
    "write_calc_result",
    "write_evidence_ref",
    "write_employee_document",
    "write_llm_log",
    # identity resolution + document (blob) storage
    "add_identifier",
    "resolve_employee",
    "store_document",
    "write_document",
    "add_doc_link",
    "documents_of",
    "fetch_blob",
    # exact-SQL retrieval (numeric path -- never similarity)
    "get_employee",
    "get_person_month",
    "get_calc",
    "get_evidence",
    "list_verdicts",
    "get_verdict",
    "get_gate_results",
    "get_llm_log",
    "list_employees",
    "get_person_months",
    "list_evidence",
    "documents_for",
    "find_employees",
    # high-level write-through of a whole pipeline result
    "persist_result",
]


def month_str(year: int, month: int) -> str:
    """Canonical 'YYYY-MM' used by figure_key / doc_link.month."""
    return f"{year:04d}-{month:02d}"


# ---------------------------------------------------------------------------
# Write-through. All UPSERTs; the connection is committed by the caller
# unless commit=True.
# ---------------------------------------------------------------------------
def upsert_entity(
    conn: sqlite3.Connection,
    entity_id: str,
    base_uen: Optional[str] = None,
    display_name: Optional[str] = None,
    commit: bool = False,
) -> None:
    conn.execute(
        "INSERT INTO entity (entity_id, base_uen, display_name) VALUES (?,?,?) "
        "ON CONFLICT(entity_id) DO UPDATE SET base_uen=excluded.base_uen, "
        "display_name=excluded.display_name",
        (entity_id, base_uen, display_name or entity_id),
    )
    if commit:
        conn.commit()


def write_employee(
    conn: sqlite3.Connection, emp: Employee, commit: bool = False
) -> None:
    """Persist an Employee. Ensures the parent entity row exists (FK).

    Also registers the employee's own id (and NRIC, if present) in
    ``employee_identifier`` so the chatbot can later resolve a person by either
    handle to the canonical ``employee_id`` (see :func:`resolve_employee`).
    """
    upsert_entity(conn, emp.entity)
    conn.execute(
        "INSERT INTO employee (employee_id, name, entity_id, nric, citizenship, "
        "ecmf_validated, no_other_grant, designation, hire_type, "
        "normalized_name, confidence, confidence_reason) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(employee_id) DO UPDATE SET "
        "name=excluded.name, entity_id=excluded.entity_id, nric=excluded.nric, "
        "citizenship=excluded.citizenship, ecmf_validated=excluded.ecmf_validated, "
        "no_other_grant=excluded.no_other_grant, designation=excluded.designation, "
        "hire_type=excluded.hire_type, normalized_name=excluded.normalized_name, "
        "confidence=excluded.confidence, confidence_reason=excluded.confidence_reason",
        (
            emp.id,
            emp.name,
            emp.entity,
            getattr(emp, "nric", None),
            emp.citizenship.value,
            int(emp.ecmf_validated),
            int(emp.no_other_grant),
            emp.designation,
            emp.hire_type.value if emp.hire_type is not None else None,
            emp.normalized_name,
            emp.confidence,
            emp.confidence_reason,
        ),
    )
    add_identifier(conn, "employee_id", emp.id, emp.id)
    if getattr(emp, "nric", None):
        add_identifier(conn, "nric", emp.nric, emp.id)
    if commit:
        conn.commit()


def write_person_month(
    conn: sqlite3.Connection, pm: PersonMonth, commit: bool = False
) -> None:
    conn.execute(
        "INSERT INTO person_month (employee_id, year, month, basic_salary, "
        "hours, confidence, confidence_reason) VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(employee_id, year, month) DO UPDATE SET "
        "basic_salary=excluded.basic_salary, hours=excluded.hours, "
        "confidence=excluded.confidence, confidence_reason=excluded.confidence_reason",
        (
            pm.employee_id,
            pm.year,
            pm.month,
            pm.basic_salary,
            pm.hours,
            pm.confidence,
            pm.confidence_reason,
        ),
    )
    if commit:
        conn.commit()


def write_employee_document(conn: sqlite3.Connection, cell, commit: bool = False) -> None:
    """Persist one FR-2 completeness cell as an employee's document status.

    Entity-scope cells (no ``employee_id``) are skipped — they aren't per-person.
    The source file/cell are stored when the document is present, so the chatbot
    can later fetch the evidence by exact-SQL from a future session.
    """
    if not getattr(cell, "employee_id", None):
        return
    ref = cell.source_ref
    conn.execute(
        "INSERT INTO employee_document (employee_id, doc_type, month, status, severity, "
        "file, sheet, cell, reason) VALUES (?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(employee_id, doc_type, month) DO UPDATE SET "
        "status=excluded.status, severity=excluded.severity, file=excluded.file, "
        "sheet=excluded.sheet, cell=excluded.cell, reason=excluded.reason",
        (
            cell.employee_id, cell.doc_type.value, cell.month or 0, cell.status.value,
            cell.severity.value, ref.file if ref else None, ref.sheet if ref else None,
            ref.cell_or_row if ref else None, cell.reason,
        ),
    )
    if commit:
        conn.commit()


def documents_for(conn: sqlite3.Connection, employee_id: str) -> list:
    """All stored document statuses for one employee (present + missing).

    Exact-SQL retrieval (never similarity) so the chatbot can answer "which
    documents are on file for X / what's missing" deterministically.
    """
    rows = conn.execute(
        "SELECT doc_type, month, status, severity, file, sheet, cell, reason "
        "FROM employee_document WHERE employee_id=? ORDER BY doc_type, month",
        (employee_id,),
    ).fetchall()
    return [
        {"doc_type": r[0], "month": r[1], "status": r[2], "severity": r[3],
         "file": r[4], "sheet": r[5], "cell": r[6], "reason": r[7]}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Identity resolution + document (blob) storage. This is the "store documents
# by employee id OR nric, fetch them back through the chatbot" path. Documents
# are partitioned by employee via the existing doc_link bridge; the bytes live
# in doc_blob. All writes are UPSERTs (idempotent / deterministic, PRD §9).
# ---------------------------------------------------------------------------
def _norm_id(value: str) -> str:
    """Canonicalise an external handle for exact matching (upper, trimmed).

    Applied to both stored identifiers and the query, so 's1234567a',
    ' S1234567A ' and 'S1234567A' all resolve to the same person.
    """
    return re.sub(r"\s+", "", (value or "").strip().upper())


def add_identifier(
    conn: sqlite3.Connection,
    id_type: str,
    id_value: str,
    employee_id: str,
    commit: bool = False,
) -> None:
    """Register one lookup handle (nric/fin/payroll_id/email/...) -> employee_id.

    The value is normalized before storage so lookups are case/space-insensitive.
    Blank values are ignored. Re-adding the same (type, value) updates the target.
    """
    norm = _norm_id(id_value)
    if not norm:
        return
    conn.execute(
        "INSERT INTO employee_identifier (id_type, id_value, employee_id) "
        "VALUES (?,?,?) ON CONFLICT(id_type, id_value) DO UPDATE SET "
        "employee_id=excluded.employee_id",
        (id_type, norm, employee_id),
    )
    if commit:
        conn.commit()


def resolve_employee(
    conn: sqlite3.Connection, handle: str
) -> Optional[str]:
    """Resolve any handle HR types (employee_id, NRIC, FIN, email, ...) to the
    canonical ``employee_id`` — the entry point for a "documents for <X>" chat.

    Exact, normalized lookup against ``employee_identifier`` (never similarity),
    trying the raw handle first, then its normalized form. Returns ``None`` if
    nothing matches (the caller may then fall back to :func:`find_employees` for
    a fuzzy name match). Stable: if several id_types share a value, the lowest
    id_type/employee_id pair wins.
    """
    if not handle:
        return None
    for candidate in (handle, _norm_id(handle)):
        row = conn.execute(
            "SELECT employee_id FROM employee_identifier WHERE id_value=? "
            "ORDER BY id_type, employee_id LIMIT 1",
            (candidate,),
        ).fetchone()
        if row is not None:
            return row["employee_id"]
    return None


def write_document(
    conn: sqlite3.Connection,
    doc_id: str,
    file: str,
    content: bytes,
    *,
    doc_type: Optional[str] = None,
    sheet: Optional[str] = None,
    mime_type: Optional[str] = None,
    orig_filename: Optional[str] = None,
    uploaded_at: Optional[str] = None,
    content_hash: Optional[str] = None,
    commit: bool = False,
) -> None:
    """Persist one document's metadata + bytes (``document`` + ``doc_blob``).

    ``content_hash`` defaults to sha256(content) for dedup/determinism.
    ``uploaded_at`` is PASSED IN (ISO ts) — never generated here (PRD §9). Both
    tables UPSERT so re-storing identical bytes under the same ``doc_id`` is a
    no-op.
    """
    digest = content_hash if content_hash is not None else hashlib.sha256(content).hexdigest()
    conn.execute(
        "INSERT INTO document (doc_id, file, doc_type, sheet, content_hash, "
        "mime_type, byte_size, orig_filename, uploaded_at) "
        "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(doc_id) DO UPDATE SET "
        "file=excluded.file, doc_type=excluded.doc_type, sheet=excluded.sheet, "
        "content_hash=excluded.content_hash, mime_type=excluded.mime_type, "
        "byte_size=excluded.byte_size, orig_filename=excluded.orig_filename, "
        "uploaded_at=excluded.uploaded_at",
        (doc_id, file, doc_type, sheet, digest, mime_type, len(content),
         orig_filename, uploaded_at),
    )
    conn.execute(
        "INSERT INTO doc_blob (doc_id, content) VALUES (?,?) "
        "ON CONFLICT(doc_id) DO UPDATE SET content=excluded.content",
        (doc_id, content),
    )
    if commit:
        conn.commit()


def add_doc_link(
    conn: sqlite3.Connection,
    doc_id: str,
    employee_id: str,
    *,
    month: Optional[str] = None,
    locator: Optional[str] = None,
    commit: bool = False,
) -> None:
    """Attach a stored document to an employee (the partition bridge).

    A per-person payslip gets one link; a shared workbook (one ``document`` row)
    is linked once per employee it covers. ``month`` is 'YYYY-MM' or ``None`` for
    a whole-doc link (stored as '' so it fits the NOT-NULL-in-PK bridge).
    """
    conn.execute(
        "INSERT INTO doc_link (doc_id, employee_id, month, locator) "
        "VALUES (?,?,?,?) ON CONFLICT(doc_id, employee_id, month) DO UPDATE SET "
        "locator=excluded.locator",
        (doc_id, employee_id, month or "", locator),
    )
    if commit:
        conn.commit()


def store_document(
    conn: sqlite3.Connection,
    employee_id: str,
    file: str,
    content: bytes,
    *,
    doc_type: Optional[str] = None,
    month: Optional[str] = None,
    sheet: Optional[str] = None,
    mime_type: Optional[str] = None,
    orig_filename: Optional[str] = None,
    uploaded_at: Optional[str] = None,
    locator: Optional[str] = None,
    doc_id: Optional[str] = None,
    commit: bool = False,
) -> str:
    """High-level: store a document AND link it to an employee in one call.

    Returns the ``doc_id``. When ``doc_id`` is not given it is derived from the
    content hash (``doc-<sha256[:16]>``), so identical bytes dedupe to a single
    ``document`` row that many employees can link to (e.g. one shared timesheet
    workbook). This is the function the Streamlit upload handler calls.
    """
    digest = hashlib.sha256(content).hexdigest()
    did = doc_id or f"doc-{digest[:16]}"
    write_document(
        conn, did, file, content, doc_type=doc_type, sheet=sheet,
        mime_type=mime_type, orig_filename=orig_filename,
        uploaded_at=uploaded_at, content_hash=digest,
    )
    add_doc_link(conn, did, employee_id, month=month, locator=locator)
    if commit:
        conn.commit()
    return did


def documents_of(
    conn: sqlite3.Connection,
    employee_id: str,
    *,
    doc_type: Optional[str] = None,
    month: Optional[str] = None,
) -> list:
    """List the stored documents (metadata only, no blobs) for one employee.

    Joins ``doc_link`` -> ``document``. Optional exact filters by ``doc_type`` /
    ``month`` ('YYYY-MM'). Stable order (doc_type, month, doc_id) so the chatbot
    renders the same list every time. Fetch the bytes with :func:`fetch_blob`.
    """
    sql = (
        "SELECT d.doc_id, d.file, d.doc_type, d.sheet, d.mime_type, d.byte_size, "
        "d.orig_filename, d.uploaded_at, l.month, l.locator "
        "FROM doc_link l JOIN document d ON l.doc_id = d.doc_id "
        "WHERE l.employee_id=?"
    )
    params: list = [employee_id]
    if doc_type is not None:
        sql += " AND d.doc_type=?"
        params.append(doc_type)
    if month is not None:
        sql += " AND l.month=?"
        params.append(month)
    sql += " ORDER BY d.doc_type, l.month, d.doc_id"
    rows = conn.execute(sql, params).fetchall()
    return [
        {"doc_id": r["doc_id"], "file": r["file"], "doc_type": r["doc_type"],
         "sheet": r["sheet"], "mime_type": r["mime_type"], "byte_size": r["byte_size"],
         "orig_filename": r["orig_filename"], "uploaded_at": r["uploaded_at"],
         "month": r["month"] or None, "locator": r["locator"]}
        for r in rows
    ]


def fetch_blob(
    conn: sqlite3.Connection, doc_id: str
) -> Optional[Tuple[bytes, Optional[str], Optional[str]]]:
    """Return ``(content, mime_type, orig_filename)`` for a doc_id, or ``None``.

    The download path: the chatbot lists documents with :func:`documents_of`,
    then hands a chosen ``doc_id`` here to stream the actual file back to HR.
    """
    row = conn.execute(
        "SELECT b.content, d.mime_type, d.orig_filename "
        "FROM doc_blob b JOIN document d ON b.doc_id = d.doc_id "
        "WHERE b.doc_id=?",
        (doc_id,),
    ).fetchone()
    if row is None:
        return None
    return (row["content"], row["mime_type"], row["orig_filename"])


def write_evidence_ref(
    conn: sqlite3.Connection,
    employee_id: str,
    figure_key: str,
    ref: EvidenceRef,
    commit: bool = False,
) -> int:
    """Persist an EvidenceRef under a stable ``figure_key``; returns ref_id.

    ``figure_key`` is the exact-lookup handle (e.g. 'E1:2026-03:basic_salary');
    the (employee_id, figure_key) pair is unique, so re-writing updates in place.
    """
    conn.execute(
        "INSERT INTO evidence_ref (employee_id, figure_key, label, file, sheet, "
        "cell_or_row) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(employee_id, figure_key) DO UPDATE SET "
        "label=excluded.label, file=excluded.file, sheet=excluded.sheet, "
        "cell_or_row=excluded.cell_or_row",
        (employee_id, figure_key, ref.label, ref.file, ref.sheet, ref.cell_or_row),
    )
    if commit:
        conn.commit()
    row = conn.execute(
        "SELECT ref_id FROM evidence_ref WHERE employee_id=? AND figure_key=?",
        (employee_id, figure_key),
    ).fetchone()
    return int(row["ref_id"])


def write_gate_result(
    conn: sqlite3.Connection,
    employee_id: str,
    gr: GateResult,
    ref_id: Optional[int] = None,
    commit: bool = False,
) -> None:
    conn.execute(
        "INSERT INTO gate_result (employee_id, gate, passed, reason, ref_id) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT(employee_id, gate) DO UPDATE SET "
        "passed=excluded.passed, reason=excluded.reason, ref_id=excluded.ref_id",
        (employee_id, gr.gate.value, int(gr.passed), gr.reason, ref_id),
    )
    if commit:
        conn.commit()


def write_verdict(
    conn: sqlite3.Connection, v: Verdict, commit: bool = False
) -> None:
    """Persist a Verdict; failed_gates/reasons stored as stable JSON arrays."""
    failed = json.dumps([g.value for g in v.failed_gates], sort_keys=True)
    reasons = json.dumps(list(v.reasons), sort_keys=True)
    conn.execute(
        "INSERT INTO verdict (employee_id, status, failed_gates, reasons) "
        "VALUES (?,?,?,?) "
        "ON CONFLICT(employee_id) DO UPDATE SET "
        "status=excluded.status, failed_gates=excluded.failed_gates, "
        "reasons=excluded.reasons",
        (v.employee_id, v.status.value, failed, reasons),
    )
    if commit:
        conn.commit()


def _monthly_json(monthly: Sequence) -> str:
    """Serialise a tuple of frozen monthly-breakdown dataclasses deterministically."""
    rows = [asdict(m) for m in monthly]
    return json.dumps(rows, sort_keys=True)


def write_calc_result(
    conn: sqlite3.Connection,
    result,
    commit: bool = False,
) -> None:
    """Persist a MethodAResult or MethodBResult into ``calc_result``.

    The method is inferred from the type (A vs B); Method B carries the
    ``new_hire`` quirk flag, Method A stores NULL there.
    """
    if isinstance(result, MethodAResult):
        method = CalcMethod.A.value
        new_hire = None
    elif isinstance(result, MethodBResult):
        method = CalcMethod.B.value
        new_hire = int(result.new_hire)
    else:  # pragma: no cover - guard
        raise TypeError(f"unsupported calc result type: {type(result)!r}")

    conn.execute(
        "INSERT INTO calc_result (employee_id, method, qualifying_cost_total, "
        "support_rate, claim_amount, new_hire, monthly) VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(employee_id, method) DO UPDATE SET "
        "qualifying_cost_total=excluded.qualifying_cost_total, "
        "support_rate=excluded.support_rate, claim_amount=excluded.claim_amount, "
        "new_hire=excluded.new_hire, monthly=excluded.monthly",
        (
            result.employee_id,
            method,
            result.qualifying_cost_total,
            result.support_rate,
            result.claim_amount,
            new_hire,
            _monthly_json(result.monthly),
        ),
    )
    if commit:
        conn.commit()


def write_llm_log(
    conn: sqlite3.Connection,
    cache_key: str,
    prompt: str,
    *,
    created_at: str,
    employee_id: Optional[str] = None,
    purpose: Optional[str] = None,
    model: Optional[str] = None,
    response_schema: Optional[str] = None,
    raw_response: Optional[str] = None,
    parsed: Optional[str] = None,
    confidence: Optional[float] = None,
    confidence_reason: Optional[str] = None,
    run_id: Optional[str] = None,
    commit: bool = False,
) -> None:
    """Persist an LLM cache-and-replay record (FR-13/FR-14).

    ``cache_key`` = hash(prompt + model + schema) (PLAN §1). ``created_at`` is
    REQUIRED and passed in -- never generated here (determinism). This is the
    contract T15's cache must write to.
    """
    conn.execute(
        "INSERT INTO llm_log (cache_key, employee_id, purpose, model, prompt, "
        "response_schema, raw_response, parsed, confidence, confidence_reason, "
        "created_at, run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(cache_key) DO UPDATE SET "
        "raw_response=excluded.raw_response, parsed=excluded.parsed, "
        "confidence=excluded.confidence, confidence_reason=excluded.confidence_reason",
        (
            cache_key,
            employee_id,
            purpose,
            model,
            prompt,
            response_schema,
            raw_response,
            parsed,
            confidence,
            confidence_reason,
            created_at,
            run_id,
        ),
    )
    if commit:
        conn.commit()


# ---------------------------------------------------------------------------
# Exact-SQL retrieval -- the NUMERIC path for FR-12. Never similarity.
# Stable ORDER BY everywhere (determinism, PRD §9/FR-13).
# ---------------------------------------------------------------------------
def get_employee(
    conn: sqlite3.Connection, employee_id: str
) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM employee WHERE employee_id=?", (employee_id,)
    ).fetchone()


def get_person_month(
    conn: sqlite3.Connection, employee_id: str, year: int, month: int
) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM person_month WHERE employee_id=? AND year=? AND month=?",
        (employee_id, year, month),
    ).fetchone()


def get_calc(
    conn: sqlite3.Connection, employee_id: str, method: str
) -> Optional[dict]:
    """Exact lookup of a calc result (the numeric answer source for FR-12).

    ``method`` accepts 'A'/'B' or a :class:`CalcMethod`. Returns a dict with the
    ``monthly`` JSON decoded back to a list, or ``None`` if absent.
    """
    m = method.value if isinstance(method, CalcMethod) else str(method)
    row = conn.execute(
        "SELECT * FROM calc_result WHERE employee_id=? AND method=?",
        (employee_id, m),
    ).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["monthly"] = json.loads(out["monthly"]) if out["monthly"] else []
    return out


def get_evidence(
    conn: sqlite3.Connection, figure_key: str, employee_id: Optional[str] = None
) -> Sequence[sqlite3.Row]:
    """All evidence refs for a ``figure_key`` (FR-7 one-click traceability).

    ``figure_key`` is unique per employee; pass ``employee_id`` to disambiguate
    when the same key shape recurs across people. Stable ordering by employee
    then ref_id.
    """
    if employee_id is not None:
        return conn.execute(
            "SELECT * FROM evidence_ref WHERE figure_key=? AND employee_id=? "
            "ORDER BY employee_id, ref_id",
            (figure_key, employee_id),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM evidence_ref WHERE figure_key=? ORDER BY employee_id, ref_id",
        (figure_key,),
    ).fetchall()


def list_verdicts(
    conn: sqlite3.Connection, entity: Optional[str] = None
) -> Sequence[dict]:
    """All verdicts (optionally for one entity), with JSON arrays decoded.

    Stable ordering by employee_id. ``failed_gates``/``reasons`` are returned as
    Python lists.
    """
    if entity is not None:
        rows = conn.execute(
            "SELECT v.* FROM verdict v JOIN employee e "
            "ON v.employee_id = e.employee_id WHERE e.entity_id=? "
            "ORDER BY v.employee_id",
            (entity,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM verdict ORDER BY employee_id"
        ).fetchall()
    return [_decode_verdict(r) for r in rows]


def get_verdict(
    conn: sqlite3.Connection, employee_id: str
) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM verdict WHERE employee_id=?", (employee_id,)
    ).fetchone()
    return _decode_verdict(row) if row is not None else None


def _decode_verdict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["failed_gates"] = json.loads(d["failed_gates"]) if d["failed_gates"] else []
    d["reasons"] = json.loads(d["reasons"]) if d["reasons"] else []
    return d


def get_gate_results(
    conn: sqlite3.Connection, employee_id: str
) -> Sequence[sqlite3.Row]:
    """All gate results for an employee, ordered by gate code (G1..G7)."""
    return conn.execute(
        "SELECT * FROM gate_result WHERE employee_id=? ORDER BY gate",
        (employee_id,),
    ).fetchall()


def get_llm_log(
    conn: sqlite3.Connection, cache_key: str
) -> Optional[sqlite3.Row]:
    """Cache-replay lookup by ``cache_key`` (hash(prompt+model+schema))."""
    return conn.execute(
        "SELECT * FROM llm_log WHERE cache_key=?", (cache_key,)
    ).fetchone()


def list_employees(conn: sqlite3.Connection) -> Sequence[sqlite3.Row]:
    """Every persisted employee, stable order by id (FR-12 record retrieval)."""
    return conn.execute("SELECT * FROM employee ORDER BY employee_id").fetchall()


def get_person_months(
    conn: sqlite3.Connection, employee_id: str
) -> Sequence[sqlite3.Row]:
    """All person-months for an employee, chronological order."""
    return conn.execute(
        "SELECT * FROM person_month WHERE employee_id=? ORDER BY year, month",
        (employee_id,),
    ).fetchall()


def list_evidence(
    conn: sqlite3.Connection, employee_id: str
) -> Sequence[sqlite3.Row]:
    """All evidence refs for an employee (FR-7), stable order by ref_id."""
    return conn.execute(
        "SELECT * FROM evidence_ref WHERE employee_id=? ORDER BY ref_id",
        (employee_id,),
    ).fetchall()


def find_employees(
    conn: sqlite3.Connection, query_text: str
) -> Sequence[sqlite3.Row]:
    """Resolve a free-text mention to stored employee row(s) — the RAG lookup.

    Deterministic, dependency-free matching over the (small, POC-sized) roster:
      * exact: the employee_id appears verbatim in the question, OR
      * name: every token of the stored name appears in the question, OR
      * loose: a >=2-word name whose first and last token both appear.
    Returns the matches in stable id order (usually 0 or 1). The figures
    themselves are read by the caller via the exact-SQL getters, never invented.
    """
    ql = (query_text or "").lower()
    exact, loose = [], []
    for row in list_employees(conn):
        emp_id = (row["employee_id"] or "").lower()
        if emp_id and emp_id in ql:
            exact.append(row)
            continue
        name = (row["name"] or "").lower()
        toks = [t for t in re.split(r"[\s,]+", name) if t]
        if toks and all(t in ql for t in toks):
            exact.append(row)
        elif len(toks) >= 2 and toks[0] in ql and toks[-1] in ql:
            loose.append(row)
    return exact or loose


# ---------------------------------------------------------------------------
# High-level write-through: persist an entire pipeline result (FR-13).
# Duck-typed so this module keeps its layering (it never imports app/calc).
# ---------------------------------------------------------------------------
def persist_result(
    conn: sqlite3.Connection,
    result,
    *,
    commit: bool = True,
) -> int:
    """Write a whole pipeline ``result`` into the store; returns #employees written.

    ``result`` is duck-typed: anything exposing ``.entities`` where each entity has
    ``.entity`` and ``.employees``, and each employee result exposes ``.employee``,
    ``.verdict``, ``.method_a``, optional ``.method_b`` and ``.gate_evaluations``
    (the app pipeline's ``EmployeeResult``). Gates are folded to one row per code
    (preferring a failing/needs-review evaluation, which is the one that carries
    the actionable reason + source cell). All writes are UPSERTs, so re-persisting
    the same run overwrites cleanly (determinism, PRD §9). The caller owns the
    connection lifecycle; we commit once at the end unless ``commit=False``.
    """
    written = 0
    for ent in getattr(result, "entities", ()) or ():
        entity_name = getattr(ent, "entity", None) or "(unknown entity)"
        upsert_entity(conn, entity_name, display_name=entity_name)
        for e in getattr(ent, "employees", ()) or ():
            emp = e.employee
            write_employee(conn, emp)
            write_verdict(conn, e.verdict)

            # fold per-month gate evaluations -> one row per gate code
            best = {}
            for ev in getattr(e, "gate_evaluations", ()) or ():
                code = ev.gate.value
                cur = best.get(code)
                # keep the first; replace only if the new one fails and the kept one passed
                if cur is None or (cur.passed and not ev.passed):
                    best[code] = ev
            for code, ev in best.items():
                ref_id = None
                ref = ev.source_ref
                if ref is not None and ref.file:
                    figure_key = f"{emp.id}:{code}:{ref.label or code}"
                    ref_id = write_evidence_ref(conn, emp.id, figure_key, ref)
                write_gate_result(conn, emp.id, ev.result, ref_id=ref_id)

            write_calc_result(conn, e.method_a)
            if getattr(e, "method_b", None) is not None:
                write_calc_result(conn, e.method_b)
            written += 1

        # persist the per-employee document checklist (FR-2 cells) for recall
        comp = getattr(ent, "completeness", None)
        for cell in getattr(comp, "cells", ()) or ():
            write_employee_document(conn, cell)
    if commit:
        conn.commit()
    return written
