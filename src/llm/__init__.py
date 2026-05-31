"""LLM integration package.

CALLING SPEC:
    src.llm.adapter   — LLMGenerate Protocol + RoleLLMAdapter.
    src.llm.providers — AgentProvider ABC and ClaudeCodeProvider.

SIDE EFFECTS:
    ClaudeCodeProvider spawns `claude` CLI subprocess.
"""

from src.llm.adapter import LLMGenerate, RoleLLMAdapter

__all__ = ["LLMGenerate", "RoleLLMAdapter"]
