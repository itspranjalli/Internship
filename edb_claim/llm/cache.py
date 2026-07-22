"""LLM cache-and-replay store — the determinism guarantee (PRD §7, §9, FR-13).

CLAUDE.md hard rule: *the cache-and-replay log is the actual determinism
guarantee*, not the temperature setting. GPU inference at temp 0 is not
bit-exact, so the only way "same inputs -> identical outputs" (PRD §9) holds is
by keying each call on a stable hash of ``(prompt, model, schema)`` and replaying
the stored result on a hit. This module is that store.

It is deliberately a small **local JSON file** for the POC. The eventual home is
the FR-13 ``llm_log`` SQLite table (T22); the record shape here is kept
compatible with that table (see :class:`LLMRecord` / :func:`LLMRecord.to_row`) so
T22 can migrate without reshaping the data.

No third-party dependency, no nondeterminism in the key: keys are SHA-256 over a
canonical JSON serialisation (``sort_keys=True``, fixed separators) — never
``time.time()``/random (PRD §9). Timestamps ARE recorded inside each record for
the audit trail, but they are *not* part of the cache key.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple


# ---------------------------------------------------------------------------
# Stable hashing (PRD §9 — no nondeterminism in the key)
# ---------------------------------------------------------------------------
def _canonical(obj: Any) -> str:
    """Canonical JSON: sorted keys, compact separators, non-ASCII preserved.

    Identical inputs -> byte-identical string -> identical hash across runs and
    machines. ``default=str`` lets enums/dates/etc. serialise deterministically
    without exploding (they render to their stable ``str``).
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def cache_key(prompt: str, model: Optional[str], schema: Optional[Mapping[str, Any]]) -> str:
    """Stable SHA-256 key for one LLM call.

    Keyed on exactly ``(prompt, model, schema)`` — the inputs that determine the
    answer. ``source_ref`` / ``confidence_hint`` are provenance, NOT key
    material: the same prompt+schema against the same model must replay the same
    answer regardless of which document occasioned it.
    """
    payload = {
        "prompt": prompt,
        "model": model,
        "schema": schema,
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Cache record — shape compatible with the future FR-13 ``llm_log`` table (T22)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LLMRecord:
    """One persisted LLM interaction = one ``llm_log`` row (FR-13, T22).

    Carries everything the auditor needs to see "how any value entered the
    system" (PRD §7): the cache key, prompt, raw response, parsed result, the
    confidence + its plain-language reason (FR-14: never discarded), and the
    source-document reference (FR-7). ``model`` and ``created_at`` round out the
    audit trail; ``created_at`` is recorded but is NOT part of the cache key.
    """

    key: str                                   # cache_key(prompt, model, schema)
    model: Optional[str]                       # config.llm_model (provider-agnostic)
    prompt: str                                # exact prompt sent (PRD §7 persisted)
    raw_response: Optional[str]                # raw model text (PRD §7 persisted)
    parsed: Optional[Dict[str, Any]]           # schema-validated JSON result
    confidence: Optional[float] = None         # 0-1 (FR-9/FR-14)
    confidence_reason: Optional[str] = None    # plain-language reason (FR-14: never discard)
    source_ref: Optional[Dict[str, Any]] = None  # {file,sheet,cell/row,...} (FR-7)
    schema_name: Optional[str] = None          # optional schema label for the audit trail
    created_at: Optional[str] = None           # ISO timestamp; audit only, NOT in key

    def to_row(self) -> Dict[str, Any]:
        """Render as a plain dict — the prospective ``llm_log`` row (T22).

        Nested dicts (``parsed``, ``source_ref``) are JSON-encoded so the shape
        maps onto SQLite TEXT columns without further transformation.
        """
        row = asdict(self)
        row["parsed"] = json.dumps(self.parsed, sort_keys=True) if self.parsed is not None else None
        row["source_ref"] = (
            json.dumps(self.source_ref, sort_keys=True) if self.source_ref is not None else None
        )
        return row


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------
class LLMCache:
    """Local JSON-file cache of :class:`LLMRecord` keyed by :func:`cache_key`.

    POC-grade and dependency-free: the whole store is a single JSON object on
    disk (``{key: record}``). ``get``/``put`` replay/persist records; writes are
    atomic (temp file + ``os.replace``) so a crash mid-write cannot corrupt the
    store. An in-memory-only store is available by passing ``path=None`` (used by
    tests and by the no-endpoint path that need never touch disk).
    """

    def __init__(self, path: Optional[str]):
        self.path = path
        self._data: Dict[str, Dict[str, Any]] = {}
        self._load()

    # -- persistence ------------------------------------------------------
    def _load(self) -> None:
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                self._data = loaded
        except (json.JSONDecodeError, OSError):
            # A corrupt/unreadable cache must not crash the pipeline; start empty
            # and let it repopulate (graceful degradation, CLAUDE.md).
            self._data = {}

    def _flush(self) -> None:
        if not self.path:
            return
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        # Atomic write: serialise to a temp file in the same dir, then replace.
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, sort_keys=True, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    # -- API --------------------------------------------------------------
    def get(self, key: str) -> Optional[LLMRecord]:
        """Replay a stored record, or ``None`` on a miss."""
        row = self._data.get(key)
        if row is None:
            return None
        return LLMRecord(**row)

    def put(self, record: LLMRecord) -> None:
        """Persist (idempotently overwrite) a record under its key."""
        self._data[record.key] = asdict(record)
        self._flush()

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)
