"""Tests for AgentProvider implementations.

Uses mocks for subprocess and API calls — no real LLM invocations.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.llm.providers.base import AgentProvider, AgentResult
from src.llm.providers.api_provider import APIProvider
from src.llm.providers.claude_code_provider import ClaudeCodeProvider
from src.llm.providers.gemini_cli_provider import GeminiCliProvider
from src.llm.providers.codex_cli_provider import CodexCliProvider


# ---------------------------------------------------------------------------
# AgentResult dataclass
# ---------------------------------------------------------------------------


class TestAgentResult:
    def test_defaults(self):
        r = AgentResult(output="hello")
        assert r.output == "hello"
        assert r.artifacts == []
        assert r.token_usage == 0
        assert r.duration_seconds == 0.0
        assert r.provider == ""

    def test_custom_fields(self):
        r = AgentResult(
            output="out",
            artifacts=[Path("/tmp/a.txt")],
            token_usage=100,
            duration_seconds=1.5,
            provider="api",
        )
        assert len(r.artifacts) == 1
        assert r.token_usage == 100
        assert r.provider == "api"


# ---------------------------------------------------------------------------
# APIProvider
# ---------------------------------------------------------------------------


class TestAPIProvider:
    def _make_mock_response(self, text: str = '{"regime": "bullish"}'):
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = text

        mock_usage = MagicMock()
        mock_usage.input_tokens = 50
        mock_usage.output_tokens = 30

        mock_response = MagicMock()
        mock_response.content = [mock_block]
        mock_response.usage = mock_usage
        return mock_response

    @patch("src.llm.providers.api_provider.anthropic.Anthropic")
    def test_execute_returns_result(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = self._make_mock_response()
        mock_anthropic_cls.return_value = mock_client

        provider = APIProvider()
        result = provider.execute("evaluate market", context={"system": "you are a analyst"})

        assert isinstance(result, AgentResult)
        assert result.output == '{"regime": "bullish"}'
        assert result.token_usage == 80
        assert result.provider == "api"
        assert result.duration_seconds >= 0

    @patch("src.llm.providers.api_provider.anthropic.Anthropic")
    def test_execute_without_system(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = self._make_mock_response()
        mock_anthropic_cls.return_value = mock_client

        provider = APIProvider()
        result = provider.execute("hello")
        assert result.output == '{"regime": "bullish"}'

        call_kwargs = mock_client.messages.create.call_args[1]
        assert "system" not in call_kwargs

    @patch("src.llm.providers.api_provider.anthropic.Anthropic")
    def test_execute_retries_on_failure(self, mock_anthropic_cls):
        mock_client = MagicMock()
        bad_block = MagicMock()
        bad_block.type = "tool_use"  # no text block

        good_block = MagicMock()
        good_block.type = "text"
        good_block.text = "ok"

        mock_usage = MagicMock()
        mock_usage.input_tokens = 10
        mock_usage.output_tokens = 5

        mock_client.messages.create.side_effect = [
            MagicMock(content=[bad_block], usage=mock_usage),
            MagicMock(content=[good_block], usage=mock_usage),
        ]
        mock_anthropic_cls.return_value = mock_client

        provider = APIProvider(max_retries=3)
        result = provider.execute("test")
        assert result.output == "ok"

    @patch("src.llm.providers.api_provider.anthropic.Anthropic")
    def test_execute_raises_after_max_retries(self, mock_anthropic_cls):
        mock_client = MagicMock()
        bad_block = MagicMock()
        bad_block.type = "tool_use"
        mock_client.messages.create.return_value = MagicMock(
            content=[bad_block], usage=MagicMock(input_tokens=0, output_tokens=0)
        )
        mock_anthropic_cls.return_value = mock_client

        provider = APIProvider(max_retries=2)
        with pytest.raises(ValueError, match="Failed after 2 retries"):
            provider.execute("test")


# ---------------------------------------------------------------------------
# ClaudeCodeProvider
# ---------------------------------------------------------------------------


class TestClaudeCodeProvider:
    @patch("src.llm.providers.claude_code_provider.subprocess.run")
    def test_execute_json_output(self, mock_run):
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

    @patch("src.llm.providers.claude_code_provider.subprocess.run")
    def test_execute_raw_output_fallback(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="raw text output",
            stderr="",
        )
        provider = ClaudeCodeProvider()
        result = provider.execute("test")
        assert result.output == "raw text output"

    @patch("src.llm.providers.claude_code_provider.subprocess.run")
    def test_execute_raises_on_nonzero_exit(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error msg")
        provider = ClaudeCodeProvider()
        with pytest.raises(RuntimeError, match="exited 1"):
            provider.execute("test")

    @patch("src.llm.providers.claude_code_provider.subprocess.run")
    def test_execute_includes_system_in_prompt(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        provider = ClaudeCodeProvider()
        provider.execute("task", context={"system": "sys prompt"})

        cmd = mock_run.call_args[0][0]
        prompt_arg = cmd[cmd.index("--prompt") + 1]
        assert "sys prompt" in prompt_arg
        assert "task" in prompt_arg


# ---------------------------------------------------------------------------
# GeminiCliProvider
# ---------------------------------------------------------------------------


class TestGeminiCliProvider:
    @patch("src.llm.providers.gemini_cli_provider.subprocess.run")
    def test_execute_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="gemini result", stderr="")
        provider = GeminiCliProvider()
        result = provider.execute("test")

        assert result.output == "gemini result"
        assert result.provider == "gemini_cli"

    @patch("src.llm.providers.gemini_cli_provider.subprocess.run")
    def test_execute_raises_on_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="bad")
        provider = GeminiCliProvider()
        with pytest.raises(RuntimeError, match="gemini CLI exited 1"):
            provider.execute("test")


# ---------------------------------------------------------------------------
# CodexCliProvider
# ---------------------------------------------------------------------------


class TestCodexCliProvider:
    @patch("src.llm.providers.codex_cli_provider.subprocess.run")
    def test_execute_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="codex result", stderr="")
        provider = CodexCliProvider()
        result = provider.execute("test")

        assert result.output == "codex result"
        assert result.provider == "codex_cli"

    @patch("src.llm.providers.codex_cli_provider.subprocess.run")
    def test_execute_raises_on_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="bad")
        provider = CodexCliProvider()
        with pytest.raises(RuntimeError, match="codex CLI exited 1"):
            provider.execute("test")


# ---------------------------------------------------------------------------
# ABC contract
# ---------------------------------------------------------------------------


class TestProviderABC:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            AgentProvider()

    def test_all_providers_are_subclasses(self):
        assert issubclass(APIProvider, AgentProvider)
        assert issubclass(ClaudeCodeProvider, AgentProvider)
        assert issubclass(GeminiCliProvider, AgentProvider)
        assert issubclass(CodexCliProvider, AgentProvider)
