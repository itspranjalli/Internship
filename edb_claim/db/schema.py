"""FR-13 SQLite schema for the EDB RIS(C) persistence & retrieval store.

Single local file (``config.db_path``), stdlib :mod:`sqlite3` only for the
relational core; ``sqlite-vec`` is loaded (best-effort) for the vector table.

Design rules (PRD FR-13, §9; CLAUDE.md "Persistence"/"Determinism"):
  * ``employee_id`` is the **partition key** — every document, figure and chunk
    row carries it. Shared inputs (the entity-wide timesheet workbook) attach to
    many employees via the ``doc_link(doc_id, employee_id, month)`` bridge.
  * Idempotent: every object is ``CREATE ... IF NOT EXISTS`` so re-running
    :func:`init_db` on an existing file is a no-op.
  * No nondeterminism baked into the schema — there are **no** ``DEFAULT
    CURRENT_TIMESTAMP`` / random columns. Timestamps and run ids are *passed in*
    by the caller (from the run manifest), never generated here, so identical
    inputs yield byte-identical rows (PRD §9).
  * ``evidence_ref`` backs FR-7 one-click traceability; ``llm_log`` is the
    FR-9→12 cache-and-replay + audit trail (FR-14).

Vector table:
  We try to ``import sqlite_vec`` and create a ``vec0`` virtual table for
  ``chunk_vec``. If the extension cannot be loaded in the host environment, we
  fall back to a plain ``chunk_vec(chunk_id, embedding BLOB)`` table so the rest
  of the schema is usable; **T23** (chunking + embedding) finalizes the vector
  table and the embedding dimension. :func:`init_db` reports which path was used
  via the returned :class:`SchemaInfo`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

try:  # best-effort; finalized by T23
    import sqlite_vec  # type: ignore
except Exception:  # pragma: no cover - depends on host wheels
    sqlite_vec = None  # type: ignore


# Default embedding dimension. all-MiniLM-L6-v2 (config.embedding_model) emits
# 384-d vectors. T23 owns the final value; kept here so the vec0 table has a
# concrete width. ASSUMED until T23 wires the real embedder.
DEFAULT_EMBEDDING_DIM = 384


@dataclass(frozen=True)
class SchemaInfo:
    """What :func:`init_db` built — reported so callers/tests can branch.

    ``vec_backend`` is ``"vec0"`` when the sqlite-vec virtual table was created,
    or ``"placeholder"`` when the plain-BLOB fallback was used (T23 finalizes).
    """

    vec_backend: str               # "vec0" | "placeholder"
    embedding_dim: int
    sqlite_vec_loaded: bool


# ---------------------------------------------------------------------------
# Relational core (stdlib sqlite3). employee_id is the partition key.
# ---------------------------------------------------------------------------
_CORE_DDL = """
-- Participating entity (config.PARTICIPATING_ENTITIES). UEN/base optional.
CREATE TABLE IF NOT EXISTS entity (
    entity_id   TEXT PRIMARY KEY,      -- participating-entity name/code
    base_uen    TEXT,                  -- base UEN this centre rolls up to (nullable)
    display_name TEXT
);

-- A person on an entity roster. employee_id = FR-13 partition key.
CREATE TABLE IF NOT EXISTS employee (
    employee_id     TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    entity_id       TEXT NOT NULL,
    nric            TEXT,              -- canonical NRIC/FIN (local-only PII), nullable
    citizenship     TEXT NOT NULL,     -- Citizen | PR | Foreigner (domain.Citizenship)
    ecmf_validated  INTEGER NOT NULL,  -- 0/1 (G2)
    no_other_grant  INTEGER NOT NULL,  -- 0/1 (G3)
    designation     TEXT,              -- free-text, judged for G5
    hire_type       TEXT,              -- New Hire | Upskilled | Reskilled
    normalized_name TEXT,              -- FR-11 reconciliation key
    confidence      REAL,              -- LLM provenance (FR-10/11/14), nullable
    confidence_reason TEXT,
    FOREIGN KEY (entity_id) REFERENCES entity(entity_id)
);

-- Any external handle HR might use to name a person, mapped to the partition
-- key. This is how the chatbot fetches documents "by employee id OR nric OR any
-- such": the id the user types is normalized (upper, trimmed) and resolved here
-- to the canonical employee_id before the document lookup runs. One person may
-- have several rows (employee_id, nric, fin, payroll_id, email, name_alias).
CREATE TABLE IF NOT EXISTS employee_identifier (
    id_type     TEXT NOT NULL,        -- 'employee_id'|'nric'|'fin'|'payroll_id'|'email'|'name_alias'
    id_value    TEXT NOT NULL,        -- normalized value (upper/trim; NRIC 'S1234567A')
    employee_id TEXT NOT NULL,        -- canonical partition key it resolves to
    PRIMARY KEY (id_type, id_value),
    FOREIGN KEY (employee_id) REFERENCES employee(employee_id)
);
CREATE INDEX IF NOT EXISTS ix_ident_employee ON employee_identifier(employee_id);

-- A source document (payslip, timesheet workbook, ECMF list, ...). A shared
-- workbook is ONE document row, attached to many employees via doc_link.
CREATE TABLE IF NOT EXISTS document (
    doc_id     TEXT PRIMARY KEY,
    file       TEXT NOT NULL,          -- filename / path (FR-7 {source file})
    doc_type   TEXT,                   -- payslip | timesheet | ecmf | cpf | bank ...
    sheet      TEXT,                   -- worksheet name when tabular (nullable)
    content_hash TEXT,                 -- sha256 of bytes: dedup + determinism (nullable)
    mime_type  TEXT,                   -- 'application/pdf' | 'image/png' ... (nullable)
    byte_size  INTEGER,                -- length of the stored blob (nullable)
    orig_filename TEXT,                -- filename as HR uploaded it (nullable)
    uploaded_at TEXT                   -- ISO ts PASSED IN by caller, never generated
);

-- Actual document bytes, one row per document, kept in a separate table so
-- metadata scans (documents_for / list) never drag the blobs into memory; the
-- bytes are read only on an explicit fetch_blob() download. content is the raw
-- file exactly as uploaded (local-only store, CLAUDE.md: no external calls).
CREATE TABLE IF NOT EXISTS doc_blob (
    doc_id  TEXT PRIMARY KEY,
    content BLOB NOT NULL,
    FOREIGN KEY (doc_id) REFERENCES document(doc_id)
);

-- Many-to-many bridge scoping shared documents to employee (+ optional month).
-- This is how the entity-wide timesheet workbook is partitioned per employee.
CREATE TABLE IF NOT EXISTS doc_link (
    doc_id      TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    month       TEXT,                  -- 'YYYY-MM' or NULL (whole-doc link)
    locator     TEXT,                  -- row/range within the doc for this person
    PRIMARY KEY (doc_id, employee_id, month),
    FOREIGN KEY (doc_id) REFERENCES document(doc_id),
    FOREIGN KEY (employee_id) REFERENCES employee(employee_id)
);

-- Per-employee document status (FR-2 completeness matrix, persisted for recall).
-- One row per (employee, document type, month) so the chatbot can later answer
-- "which documents are on file for X / what's missing" by exact-SQL — surviving
-- across sessions. month = 0 for non-monthly (per-person / per-entity) docs.
CREATE TABLE IF NOT EXISTS employee_document (
    employee_id TEXT NOT NULL,
    doc_type    TEXT NOT NULL,
    month       INTEGER NOT NULL DEFAULT 0,   -- 1-12, or 0 for whole-person docs
    status      TEXT,                          -- present | missing | inconsistent
    severity    TEXT,                          -- BLOCKER | WARNING | NONE
    file        TEXT,                          -- source file when present
    sheet       TEXT,
    cell        TEXT,                          -- source cell when present
    reason      TEXT,
    PRIMARY KEY (employee_id, doc_type, month)
);
CREATE INDEX IF NOT EXISTS ix_empdoc_employee ON employee_document(employee_id);

-- One employee x one month: the eligibility/calculation unit (PRD §6).
CREATE TABLE IF NOT EXISTS person_month (
    employee_id  TEXT NOT NULL,
    year         INTEGER NOT NULL,
    month        INTEGER NOT NULL,     -- 1-12
    basic_salary REAL NOT NULL,        -- basic monthly salary only (PRD §6)
    hours        REAL NOT NULL,        -- project hours that month
    confidence   REAL,
    confidence_reason TEXT,
    PRIMARY KEY (employee_id, year, month),
    FOREIGN KEY (employee_id) REFERENCES employee(employee_id)
);

-- Outcome of a single gate G1-G7 for an employee (PRD §6, FR-3).
CREATE TABLE IF NOT EXISTS gate_result (
    employee_id TEXT NOT NULL,
    gate        TEXT NOT NULL,         -- G1..G7 (domain.GateCode)
    passed      INTEGER NOT NULL,      -- 0/1
    reason      TEXT,                  -- grounded explanation (FR-3/11)
    ref_id      INTEGER,               -- -> evidence_ref.ref_id (FR-7), nullable
    PRIMARY KEY (employee_id, gate),
    FOREIGN KEY (employee_id) REFERENCES employee(employee_id),
    FOREIGN KEY (ref_id) REFERENCES evidence_ref(ref_id)
);

-- One verdict per employee (PRD FR-6). Failed gates / reasons stored as
-- stable JSON arrays (deterministic, sorted by the writer).
CREATE TABLE IF NOT EXISTS verdict (
    employee_id  TEXT PRIMARY KEY,
    status       TEXT NOT NULL,        -- QUALIFIES | EXCLUDED | BLOCKED
    failed_gates TEXT,                 -- JSON array of gate codes
    reasons      TEXT,                 -- JSON array of reason strings
    FOREIGN KEY (employee_id) REFERENCES employee(employee_id)
);

-- Per-employee, per-method calc result + monthly breakdown (PRD §6, FR-4).
-- This is the NUMERIC source for FR-12 exact-SQL answers (never similarity).
CREATE TABLE IF NOT EXISTS calc_result (
    employee_id         TEXT NOT NULL,
    method              TEXT NOT NULL,  -- 'A' | 'B' (domain.CalcMethod)
    qualifying_cost_total REAL NOT NULL,
    support_rate        REAL NOT NULL,
    claim_amount        REAL NOT NULL,
    new_hire            INTEGER,        -- Method B quirk flag (nullable for A)
    monthly             TEXT,           -- JSON: stable list of monthly breakdown dicts
    PRIMARY KEY (employee_id, method),
    FOREIGN KEY (employee_id) REFERENCES employee(employee_id)
);

-- Every figure -> {source file, sheet, cell/row} (PRD FR-7). figure_key is the
-- stable lookup handle used by get_evidence(figure_key), e.g.
-- 'E123:2026-03:basic_salary' or 'E123:A:claim_amount'.
CREATE TABLE IF NOT EXISTS evidence_ref (
    ref_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    figure_key  TEXT NOT NULL,         -- stable handle for exact lookup
    label       TEXT,                  -- which field this backs (e.g. basic_salary)
    file        TEXT NOT NULL,         -- {source file}
    sheet       TEXT,                  -- {sheet}
    cell_or_row TEXT,                  -- {cell/row}: "I5" / row idx / locator
    FOREIGN KEY (employee_id) REFERENCES employee(employee_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_figure
    ON evidence_ref(employee_id, figure_key);

-- FR-9->12 LLM cache-and-replay + audit trail (FR-14). Keyed by the content
-- hash of (prompt + model + schema) so reruns replay identically (PRD §9).
-- Shape kept compatible with the T15 cache record (see store.py docstring):
-- T15 is not yet implemented, so this is the canonical shape T15 must match.
CREATE TABLE IF NOT EXISTS llm_log (
    cache_key   TEXT PRIMARY KEY,      -- hash(prompt + model + schema)
    employee_id TEXT,                  -- partition scope (nullable for global calls)
    purpose     TEXT,                  -- extract | designation | reconcile | qa
    model       TEXT,
    prompt      TEXT NOT NULL,
    response_schema TEXT,              -- JSON schema the call was constrained to
    raw_response TEXT,                 -- raw model output
    parsed      TEXT,                  -- parsed/validated JSON
    confidence  REAL,
    confidence_reason TEXT,
    created_at  TEXT,                  -- ISO ts PASSED IN by caller (not generated)
    run_id      TEXT,                  -- -> run_manifest.run_id
    FOREIGN KEY (employee_id) REFERENCES employee(employee_id)
);

-- One row per pipeline run (PLAN manifest.py). Timestamps live here and are
-- the only source of "now" — the rest of the schema borrows run_id/created_at.
CREATE TABLE IF NOT EXISTS run_manifest (
    run_id        TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,       -- ISO ts PASSED IN (manifest owns time)
    config_hash   TEXT,                -- hash of config.settings (determinism)
    support_rate  REAL,
    support_rate_is_final INTEGER,
    code_version  TEXT,
    notes         TEXT
);

-- Text chunk for vector retrieval (FR-13 narrative path). employee_id-scoped.
CREATE TABLE IF NOT EXISTS chunk (
    chunk_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,         -- partition key (metadata filter)
    doc_id      TEXT,                  -- source document
    doc_type    TEXT,                  -- metadata filter (FR-13 two-path)
    month       TEXT,                  -- 'YYYY-MM' metadata filter (nullable)
    text        TEXT NOT NULL,
    FOREIGN KEY (employee_id) REFERENCES employee(employee_id),
    FOREIGN KEY (doc_id) REFERENCES document(doc_id)
);

-- Helpful indexes for the deterministic exact-SQL retrieval path.
CREATE INDEX IF NOT EXISTS ix_pm_employee ON person_month(employee_id);
CREATE INDEX IF NOT EXISTS ix_calc_employee ON calc_result(employee_id);
CREATE INDEX IF NOT EXISTS ix_evidence_employee ON evidence_ref(employee_id);
CREATE INDEX IF NOT EXISTS ix_verdict_status ON verdict(status);
CREATE INDEX IF NOT EXISTS ix_chunk_filter ON chunk(employee_id, doc_type, month);
CREATE INDEX IF NOT EXISTS ix_doclink_employee ON doc_link(employee_id);
"""


# Columns added after the first schema shipped. init_db() back-fills these on
# an existing DB (SQLite has no "ADD COLUMN IF NOT EXISTS"), so re-running on the
# live edb_claim.db upgrades it in place without a rebuild. Idempotent: a column
# that already exists is skipped.
_MIGRATIONS = {
    "employee": [("nric", "TEXT")],
    "document": [
        ("content_hash", "TEXT"),   # was already present on fresh DBs; safe no-op
        ("mime_type", "TEXT"),
        ("byte_size", "INTEGER"),
        ("orig_filename", "TEXT"),
        ("uploaded_at", "TEXT"),
    ],
}


def _migrate(conn: sqlite3.Connection) -> None:
    """Add any columns missing from an older DB (see :data:`_MIGRATIONS`)."""
    for table, cols in _MIGRATIONS.items():
        existing = {
            row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for name, decl in cols:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def _create_vec_table(conn: sqlite3.Connection, dim: int) -> SchemaInfo:
    """Create ``chunk_vec``; prefer a sqlite-vec ``vec0`` virtual table.

    Falls back to a plain ``chunk_vec(chunk_id, embedding BLOB)`` placeholder if
    the extension cannot be loaded, so the schema stays usable until T23.
    """
    loaded = False
    if sqlite_vec is not None:
        try:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
            loaded = True
        except Exception:
            loaded = False

    if loaded:
        # vec0 virtual tables don't support IF NOT EXISTS; guard manually.
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'chunk_vec'"
        ).fetchone()
        if not exists:
            conn.execute(
                f"CREATE VIRTUAL TABLE chunk_vec USING vec0("
                f"chunk_id INTEGER PRIMARY KEY, embedding FLOAT[{dim}])"
            )
        return SchemaInfo("vec0", dim, True)

    # Placeholder — T23 finalizes the real vector table.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS chunk_vec ("
        "chunk_id INTEGER PRIMARY KEY, embedding BLOB)"
    )
    return SchemaInfo("placeholder", dim, False)


def connect(db_path: str) -> sqlite3.Connection:
    """Open a connection with FK enforcement and row access by name.

    Attempts to load sqlite-vec on the connection (no-op if unavailable) so
    callers that opened the DB directly can still query ``chunk_vec``.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if sqlite_vec is not None:
        try:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
        except Exception:
            pass
    return conn


def init_db(
    db_path: str, embedding_dim: int = DEFAULT_EMBEDDING_DIM
) -> SchemaInfo:
    """Create the full schema at ``db_path`` (idempotent). Returns SchemaInfo.

    ``embedding_dim`` sizes the vec0 column; T23 owns the final value.
    """
    conn = connect(db_path)
    try:
        conn.executescript(_CORE_DDL)
        _migrate(conn)
        info = _create_vec_table(conn, embedding_dim)
        conn.commit()
        return info
    finally:
        conn.close()


__all__ = [
    "DEFAULT_EMBEDDING_DIM",
    "SchemaInfo",
    "connect",
    "init_db",
]
