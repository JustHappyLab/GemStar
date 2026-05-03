"""LLM client package.

CALLING SPEC:
    src.llm.client   — Anthropic SDK wrapper with policy enforcement and retry.
    src.llm.adapter  — AgentProvider → LLMClient.generate() bridge.
    src.llm.providers — AgentProvider ABC and implementations.

SIDE EFFECTS:
    client makes HTTP calls to the Anthropic API.
"""

from src.llm.client import LLMClient

__all__ = ["LLMClient"]
