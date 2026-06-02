"""ClaudeCodeProvider — wraps the Claude Code CLI as an AgentProvider.

CALLING SPEC:
    ClaudeCodeProvider(model="sonnet", permission_mode="auto", timeout=300)
        .execute(task, context=None) -> AgentResult

SIDE EFFECTS:
    Spawns a subprocess running `claude`.
"""

from __future__ import annotations

import json
import re

from src.llm.providers.base import BaseCliProvider


class ClaudeCodeProvider(BaseCliProvider):
    """Runs tasks via the `claude` CLI in non-interactive mode."""

    def __init__(
        self,
        model: str = "sonnet",
        permission_mode: str = "auto",
        timeout: int = 300,
    ) -> None:
        super().__init__(provider_name="claude_code", timeout=timeout)
        self._model = model
        self._permission_mode = permission_mode

    def build_command(
        self,
        full_prompt: str,
        json_schema: dict | None = None,
    ) -> list[str]:
        cmd = [
            "claude",
            "--model", self._model,
            "--permission-mode", self._permission_mode,
            "--output-format", "json",
        ]
        if json_schema is not None:
            cmd.extend(["--json-schema", json.dumps(json_schema, ensure_ascii=False)])
        cmd.extend(["-p", full_prompt])
        return cmd

    def parse_output(
        self,
        stdout: str,
        json_schema_unwrap_key: str | None = None,
    ) -> str:
        try:
            data = json.loads(stdout)
            if isinstance(data, dict) and "structured_output" in data:
                text = data["structured_output"]
            elif isinstance(data, dict) and "result" in data:
                text = data["result"]
            else:
                text = data
        except json.JSONDecodeError:
            text = stdout
        if json_schema_unwrap_key is not None:
            unwrapped = _unwrap_structured_output(text, json_schema_unwrap_key)
            if unwrapped is text:
                raise RuntimeError(
                    "claude_code did not return structured_output for schema "
                    f"key '{json_schema_unwrap_key}': {_snippet(text)}"
                )
            text = unwrapped
        if not isinstance(text, str):
            text = json.dumps(text, ensure_ascii=False)
        # Strip markdown code fences the model may have added
        m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        return m.group(1).strip() if m else text.strip()


def _unwrap_structured_output(text: object, key: str) -> object:
    if isinstance(text, str):
        try:
            parsed = json.loads(_strip_json_fence(text))
        except json.JSONDecodeError:
            return text
    else:
        parsed = text
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict) and key in parsed:
        return parsed[key]
    return text


def _snippet(value: object, max_chars: int = 500) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False)
    compact = " ".join(value.strip().split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3] + "..."


def _strip_json_fence(text: str) -> str:
    s = text.strip()
    return re.sub(r"^```(?:json)?\s*", "", re.sub(r"\s*```$", "", s))
