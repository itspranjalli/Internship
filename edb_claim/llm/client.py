"""Provider-agnostic LLM client + cache/replay layer (PRD section 7, 9, FR-14; T15).

This is the adapter foundation the feature tasks build on (T16 extraction,
T17 designation, T18 reconcile, T19 Q&A). It does four things and nothing more:

  1. Talks to any OpenAI-compatible endpoint (vLLM-style) via the ``openai``
     client, at temperature 0 with JSON-schema-constrained output
     (``response_format`` structured outputs) and bounded retry (PRD section 7).
  2. Caches and replays every call through :mod:`edb_claim.llm.cache` so reruns
     are bit-identical -- the actual section 9 determinism guarantee (CLAUDE.md:
     the cache-replay log, not temperature, is what makes it deterministic).
  3. Degrades gracefully when no endpoint is configured (``llm_base_url`` is
     ``None`` / ``llm_enabled`` is False): a call returns a typed unavailable
     result instead of raising, so the deterministic pipeline runs with NO model
     (CLAUDE.md). Callers (T16-T19) decide their own fallback.
  4. Carries the confidence + reason on every result and never discards them
     (FR-14: "No black box, nothing discarded").

HARD BOUNDARY (CLAUDE.md / PRD section 7): the LLM never computes claim amounts.
This client only extracts/judges/answers; all arithmetic stays in ``calc/``.
Nothing in ``calc/`` or ``output/`` may import this module.

A mock/injectable ``transport`` lets tests exercise the "model present" path with
no network and no live model (the Qwen endpoint is DEFERRED).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Mapping, Optional

from edb_claim.config import Config, settings

from .cache import LLMCache, LLMRecord, cache_key


# ---------------------------------------------------------------------------
# Result type -- what every call() returns (the structured object T16-T19 read)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LLMResult:
    """Outcome of one :meth:`LLMClient.call`.

    ``ok`` is the single thing callers branch on: True when a schema-valid parsed
    result is present (whether freshly computed or replayed); False for the
    graceful unavailable case (no endpoint) or a transport/validation failure.
    Everything is carried, nothing discarded (FR-14) -- including
    ``confidence_reason`` (always preserved) and ``raw_text`` for the audit trail.
    """

    ok: bool
    parsed: Optional[Dict[str, Any]]           # schema-validated JSON, or None
    raw_text: Optional[str]                    # raw model text (audit trail, PRD section 7)
    confidence: Optional[float] = None         # 0-1 (FR-9/FR-14)
    confidence_reason: Optional[str] = None    # plain-language reason -- NEVER discarded (FR-14)
    cache_hit: bool = False                    # replayed from cache (section 9 determinism)
    source_ref: Optional[Dict[str, Any]] = None  # echoed back unchanged (FR-7)
    status: str = "ok"                         # "ok" | "unavailable" | "error"
    error: Optional[str] = None                # diagnostic when status != "ok"

    @property
    def available(self) -> bool:
        """False only for the no-endpoint graceful-unavailable case."""
        return self.status != "unavailable"


# A transport is anything callable like:
#   (prompt, model, schema, temperature) -> {"text": str, "confidence": float|None,
#                                             "confidence_reason": str|None}
# The default transport wraps the openai client; tests inject a mock.
Transport = Callable[[str, Optional[str], Optional[Mapping[str, Any]], float], Dict[str, Any]]


# ---------------------------------------------------------------------------
# Minimal, dependency-free schema validation
# ---------------------------------------------------------------------------
# ``jsonschema`` is not a project dependency (stdlib-only stance, per config.py /
# domain/models.py). We validate the subset of JSON Schema the feature tasks
# need: object ``type``, ``required`` keys, and per-property primitive ``type``.
# Anything richer is treated as "present and well-formed JSON object" -- enough to
# guarantee callers get the keys they declared, without pulling in a dependency.
_JSON_TYPES: Dict[str, tuple] = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
    "null": (type(None),),
}


def _isinstance_json(value: Any, json_type: str) -> bool:
    # bool is a subclass of int in Python; reject it for numeric JSON types.
    if json_type in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, _JSON_TYPES[json_type])


def validate_against_schema(parsed: Any, schema: Optional[Mapping[str, Any]]) -> None:
    """Lightweight structural check; raises ``ValueError`` on violation.

    A ``None`` schema means "any JSON object" (caller did not constrain).
    """
    if schema is None:
        if not isinstance(parsed, dict):
            raise ValueError("expected a JSON object")
        return

    expected = schema.get("type", "object")
    if expected in _JSON_TYPES and not _isinstance_json(parsed, expected):
        raise ValueError(f"top-level type mismatch: expected {expected!r}")

    if expected == "object" or isinstance(parsed, dict):
        if not isinstance(parsed, dict):
            raise ValueError("expected a JSON object")
        for req in schema.get("required", ()):  # type: ignore[union-attr]
            if req not in parsed:
                raise ValueError(f"missing required field: {req!r}")
        props = schema.get("properties", {})  # type: ignore[union-attr]
        for name, spec in props.items():
            if name in parsed and isinstance(spec, Mapping):
                exp_t = spec.get("type")
                if exp_t in _JSON_TYPES and not _isinstance_json(parsed[name], exp_t):
                    raise ValueError(f"field {name!r}: expected {exp_t!r}")


def _parse_json(text: Optional[str]) -> Dict[str, Any]:
    """Parse the model's text as a JSON object; raises ``ValueError`` otherwise."""
    if text is None:
        raise ValueError("empty model response")
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError("model response is not a JSON object")
    return obj


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------
class LLMClient:
    """Cache-fronted, schema-constrained, gracefully-degrading LLM adapter.

    Lifecycle of ``call``:
      cache lookup -> (hit) replay  ;  (miss) transport -> validate -> cache -> return.
    With no endpoint, ``call`` short-circuits to a cache replay if one exists,
    else a typed unavailable result -- it never raises into the pipeline.
    """

    def __init__(
        self,
        config: Config = settings,
        *,
        cache: Optional[LLMCache] = None,
        transport: Optional[Transport] = None,
        max_retries: int = 2,
    ):
        self.config = config
        self.cache = cache if cache is not None else LLMCache(self._cache_path(config))
        # An injected transport (tests / future swap) overrides endpoint detection.
        self._injected_transport = transport
        self.max_retries = max_retries

    @staticmethod
    def _cache_path(config: Config) -> str:
        """Local JSON cache path, derived from the configured db path.

        Lives next to the eventual FR-13 SQLite file (``edb_claim.db`` ->
        ``edb_claim.llm_cache.json``) so the POC store and its T22 destination
        sit together; T22 migrates this JSON into the ``llm_log`` table.
        """
        base = config.db_path or "./edb_claim.db"
        if base.endswith(".db"):
            return base[: -len(".db")] + ".llm_cache.json"
        return base + ".llm_cache.json"

    # -- transport selection ---------------------------------------------
    @property
    def transport(self) -> Optional[Transport]:
        """The active transport, or ``None`` when no model is reachable.

        Precedence: an injected transport (tests) always wins; otherwise the
        openai-backed transport is used only when ``llm_enabled`` (a base_url is
        configured). With neither, returns ``None`` -> graceful unavailable.
        """
        if self._injected_transport is not None:
            return self._injected_transport
        if self.config.llm_enabled:
            return self._openai_transport
        return None

    def _openai_transport(
        self,
        prompt: str,
        model: Optional[str],
        schema: Optional[Mapping[str, Any]],
        temperature: float,
    ) -> Dict[str, Any]:
        """Default transport: call an OpenAI-compatible (vLLM) chat endpoint.

        Imported lazily so the module imports with no live endpoint and so
        ``openai`` is only required on the model-present path. Requests JSON
        output via ``response_format``; vLLM honours a JSON-schema ``json_schema``
        when given, falling back to plain ``json_object`` otherwise.
        """
        from openai import OpenAI  # lazy import (no import-time dependency on a live endpoint)

        client = OpenAI(base_url=self.config.llm_base_url, api_key=self.config.llm_api_key)
        if schema is not None:
            response_format: Dict[str, Any] = {
                "type": "json_schema",
                "json_schema": {"name": "edb_claim_schema", "schema": dict(schema), "strict": True},
            }
        else:
            response_format = {"type": "json_object"}

        completion = client.chat.completions.create(
            model=model or "",
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            response_format=response_format,
        )
        text = completion.choices[0].message.content
        return {"text": text, "confidence": None, "confidence_reason": None}

    # -- the one public method T16-T19 use -------------------------------
    def call(
        self,
        prompt: str,
        *,
        schema: Optional[Mapping[str, Any]] = None,
        source_ref: Optional[Mapping[str, Any]] = None,
        confidence_hint: Optional[float] = None,
        schema_name: Optional[str] = None,
    ) -> LLMResult:
        """Run one cached, schema-constrained LLM call; never raises.

        ``schema`` constrains+validates the JSON output. ``source_ref`` is the
        FR-7 document pointer -- echoed back unchanged and persisted, but NOT part
        of the cache key (PRD section 9). ``confidence_hint`` is a caller-supplied
        fallback confidence used only when the model returns none. Returns an
        :class:`LLMResult`; the boolean ``ok`` is the branch point for callers.
        """
        model = self.config.llm_model
        key = cache_key(prompt, model, schema)
        src = dict(source_ref) if source_ref is not None else None

        # 1. Replay on cache hit -- bit-identical reruns (section 9), even with no endpoint.
        cached = self.cache.get(key)
        if cached is not None:
            return LLMResult(
                ok=cached.parsed is not None,
                parsed=cached.parsed,
                raw_text=cached.raw_response,
                confidence=cached.confidence,
                confidence_reason=cached.confidence_reason,
                cache_hit=True,
                # Echo the current call's source_ref (FR-7); fall back to stored.
                source_ref=src if src is not None else cached.source_ref,
                status="ok" if cached.parsed is not None else "error",
            )

        # 2. No transport (no endpoint, no injected mock) -> graceful unavailable.
        transport = self.transport
        if transport is None:
            return LLMResult(
                ok=False,
                parsed=None,
                raw_text=None,
                confidence=None,
                confidence_reason=(
                    "LLM endpoint not configured (llm_base_url is None); deterministic "
                    "pipeline continues without a model (CLAUDE.md, FR-14)."
                ),
                cache_hit=False,
                source_ref=src,
                status="unavailable",
                error="no_endpoint",
            )

        # 3. Live (or mock) call with bounded retry, then validate + cache.
        last_err: Optional[str] = None
        for _attempt in range(self.max_retries + 1):
            try:
                out = transport(prompt, model, schema, self.config.llm_temperature)
                raw_text = out.get("text")
                parsed = _parse_json(raw_text)
                validate_against_schema(parsed, schema)
            except Exception as exc:  # bounded retry; surfaced in the result, not swallowed
                last_err = f"{type(exc).__name__}: {exc}"
                continue

            confidence = out.get("confidence")
            if confidence is None:
                confidence = confidence_hint
            confidence_reason = out.get("confidence_reason")

            record = LLMRecord(
                key=key,
                model=model,
                prompt=prompt,
                raw_response=raw_text,
                parsed=parsed,
                confidence=confidence,
                confidence_reason=confidence_reason,
                source_ref=src,
                schema_name=schema_name,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            self.cache.put(record)
            return LLMResult(
                ok=True,
                parsed=parsed,
                raw_text=raw_text,
                confidence=confidence,
                confidence_reason=confidence_reason,
                cache_hit=False,
                source_ref=src,
                status="ok",
            )

        # 4. All attempts failed -- typed error, never raised into the pipeline.
        return LLMResult(
            ok=False,
            parsed=None,
            raw_text=None,
            confidence=None,
            confidence_reason=f"LLM call failed after {self.max_retries + 1} attempts: {last_err}",
            cache_hit=False,
            source_ref=src,
            status="error",
            error=last_err,
        )
