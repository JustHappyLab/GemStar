"""LLM client and sanitizer package.

CALLING SPEC:
    src.llm.client   — Anthropic SDK wrapper with policy enforcement and retry.
    src.llm.sanitizer — External text sanitizer for injection / markup stripping.

SIDE EFFECTS:
    client makes HTTP calls to the Anthropic API.
"""

from src.llm.client import LLMClient
from src.llm.sanitizer import sanitize

__all__ = ["LLMClient", "sanitize"]
