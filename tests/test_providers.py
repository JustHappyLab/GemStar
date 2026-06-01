"""Tests for supported AgentProvider implementations.

Uses subprocess mocks only; no real LLM invocations.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.llm.providers.base import AgentProvider, AgentResult, AgentTimeoutError, BaseCliProvider
from src.llm.providers.claude_code_provider import ClaudeCodeProvider


class TestAgentResult:
    def test_defaults(self) -> None:
        result = AgentResult(output="hello")

        assert result.output == "hello"
        assert result.artifacts == []
        assert result.token_usage == 0
        assert result.duration_seconds == 0.0
        assert result.provider == ""

    def test_custom_fields(self) -> None:
        result = AgentResult(
            output="out",
            artifacts=[Path("/tmp/a.txt")],
            token_usage=100,
            duration_seconds=1.5,
            provider="claude_code",
        )

        assert len(result.artifacts) == 1
        assert result.token_usage == 100
        assert result.provider == "claude_code"


class TestClaudeCodeProvider:
    @patch("src.llm.providers.base.subprocess.run")
    def test_execute_json_output(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"result": "analysis complete"}),
            stderr="",
        )
        provider = ClaudeCodeProvider()

        result = provider.execute("analyze market")

        assert result.output == "analysis complete"
        assert result.provider == "claude_code"
        assert result.duration_seconds >= 0

    @patch("src.llm.providers.base.subprocess.run")
    def test_execute_raw_output_fallback(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="raw text output",
            stderr="",
        )
        provider = ClaudeCodeProvider()

        result = provider.execute("test")

        assert result.output == "raw text output"

    @patch("src.llm.providers.base.subprocess.run")
    def test_execute_raises_on_nonzero_exit(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error msg")
        provider = ClaudeCodeProvider()

        with pytest.raises(RuntimeError, match="claude_code exited 1"):
            provider.execute("test")

    @patch("src.llm.providers.base.subprocess.run")
    def test_execute_wraps_timeout_without_prompt_dump(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["claude", "-p", "secret prompt"],
            timeout=1,
        )
        provider = ClaudeCodeProvider(timeout=1)

        with pytest.raises(AgentTimeoutError) as exc_info:
            provider.execute("secret prompt")

        message = str(exc_info.value)
        assert "timed out after 1s" in message
        assert "prompt_chars=" in message
        assert "secret prompt" not in message

    @patch("src.llm.providers.base.subprocess.run")
    def test_execute_includes_system_in_prompt(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        provider = ClaudeCodeProvider()

        provider.execute("task", context={"system": "sys prompt"})

        cmd = mock_run.call_args[0][0]
        prompt_arg = cmd[cmd.index("-p") + 1]
        assert "sys prompt" in prompt_arg
        assert "task" in prompt_arg

    def test_build_command_uses_claude_json_mode(self) -> None:
        provider = ClaudeCodeProvider(model="opus", permission_mode="acceptEdits")

        cmd = provider.build_command("prompt")

        assert cmd == [
            "claude",
            "--model",
            "opus",
            "--permission-mode",
            "acceptEdits",
            "--output-format",
            "json",
            "-p",
            "prompt",
        ]

    def test_parse_output_strips_markdown_fence(self) -> None:
        provider = ClaudeCodeProvider()
        stdout = json.dumps({"result": "```json\n{\"ok\": true}\n```"})

        assert provider.parse_output(stdout) == '{"ok": true}'


class TestProviderABC:
    def test_cannot_instantiate_abstract(self) -> None:
        with pytest.raises(TypeError):
            AgentProvider()

    def test_claude_provider_is_subclass(self) -> None:
        assert issubclass(ClaudeCodeProvider, AgentProvider)
        assert issubclass(ClaudeCodeProvider, BaseCliProvider)
