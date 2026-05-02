"""Tests for src.llm.client — mocked Anthropic API calls, no live requests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.llm.client import LLMClient


def _make_response(text: str = "Hello") -> SimpleNamespace:
    """Build a fake Messages response object."""
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block])


@pytest.fixture()
def mock_setup():
    """Provide (mock_client, mock_anthropic_cls) patched pair."""
    with patch("src.llm.client.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _make_response("ok")
        yield mock_client, mock_cls


class TestPolicyEnforcement:
    """Verify the client never passes tools to the API."""

    def test_no_tools_in_api_call(self, mock_setup: tuple) -> None:
        mock_client, _ = mock_setup
        llm = LLMClient(api_key="test-key")
        llm.generate("hello")

        call_kwargs = mock_client.messages.create.call_args[1]
        assert "tools" not in call_kwargs
        assert "tool_choice" not in call_kwargs

    def test_system_prompt_passed(self, mock_setup: tuple) -> None:
        mock_client, _ = mock_setup
        llm = LLMClient(api_key="test-key")
        llm.generate("hello", system="You are helpful.")

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["system"] == "You are helpful."

    def test_no_system_when_none(self, mock_setup: tuple) -> None:
        mock_client, _ = mock_setup
        llm = LLMClient(api_key="test-key")
        llm.generate("hello")

        call_kwargs = mock_client.messages.create.call_args[1]
        assert "system" not in call_kwargs


class TestGenerate:
    """Verify basic generate behaviour."""

    def test_returns_text(self, mock_setup: tuple) -> None:
        mock_client, _ = mock_setup
        mock_client.messages.create.return_value = _make_response("result text")

        llm = LLMClient(api_key="test-key")
        assert llm.generate("prompt") == "result text"

    def test_model_and_max_tokens(self, mock_setup: tuple) -> None:
        mock_client, _ = mock_setup
        llm = LLMClient(model="claude-sonnet-4-20250514", api_key="test-key")
        llm.generate("p")

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["model"] == "claude-sonnet-4-20250514"
        assert call_kwargs["max_tokens"] == 4096


class TestRetry:
    """Verify retry logic on validation failures."""

    def test_retries_on_value_error(self, mock_setup: tuple) -> None:
        mock_client, _ = mock_setup

        # First call returns no text blocks (triggers ValueError), second succeeds.
        empty_response = SimpleNamespace(content=[SimpleNamespace(type="tool_use", id="1")])
        ok_response = _make_response("recovered")

        mock_client.messages.create.side_effect = [empty_response, ok_response]

        llm = LLMClient(max_retries=3, api_key="test-key")
        assert llm.generate("prompt") == "recovered"
        assert mock_client.messages.create.call_count == 2

    def test_raises_after_max_retries(self, mock_setup: tuple) -> None:
        mock_client, _ = mock_setup

        empty_response = SimpleNamespace(content=[SimpleNamespace(type="tool_use", id="1")])
        mock_client.messages.create.return_value = empty_response

        llm = LLMClient(max_retries=2, api_key="test-key")
        with pytest.raises(ValueError, match="Failed after 2 retries"):
            llm.generate("prompt")

        assert mock_client.messages.create.call_count == 2
