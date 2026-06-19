"""
llm.py — thin, optional wrapper around the Anthropic Messages API.

Design rule (mirrors SYSTEM_DESIGN.md §4): the LLM is used ONLY to phrase the
response text, grounded in already-retrieved evidence. It never selects the
status/request_type label — that is always the rule-based Resolution Engine.

If ANTHROPIC_API_KEY is not set, every call returns None and the pipeline uses
its deterministic extractive fallback, so the whole system runs offline.
"""
from __future__ import annotations

from config import (
    ANTHROPIC_API_KEY,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    LLM_TEMPERATURE,
    USE_LLM,
)

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    if not USE_LLM:
        return None
    try:
        import anthropic  # imported lazily so offline runs need no dependency
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    except Exception:
        _client = None
    return _client


def is_available() -> bool:
    return _get_client() is not None


def complete(system: str, user: str) -> str | None:
    """Single deterministic (temperature=0) completion. Returns None on any
    failure so callers can fall back to deterministic logic."""
    client = _get_client()
    if client is None:
        return None
    try:
        msg = client.messages.create(
            model=LLM_MODEL,
            max_tokens=LLM_MAX_TOKENS,
            temperature=LLM_TEMPERATURE,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts = [b.text for b in msg.content if getattr(b, "type", "") == "text"]
        text = "".join(parts).strip()
        return text or None
    except Exception:
        return None
