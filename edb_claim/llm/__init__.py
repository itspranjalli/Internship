"""Isolated LLM adapter layer (PLAN.md section 1; PRD section 7, FR-9..FR-14).

The LLM proposes, deterministic Python disposes: nothing in ``calc/`` or
``output/`` may import this package. T15 ships the foundation (``client`` +
``cache``); the feature modules (extract/designation/reconcile/qa) build on it.
"""

from .cache import LLMCache, LLMRecord, cache_key
from .client import LLMClient, LLMResult, Transport, validate_against_schema

__all__ = [
    "LLMClient",
    "LLMResult",
    "Transport",
    "validate_against_schema",
    "LLMCache",
    "LLMRecord",
    "cache_key",
]
