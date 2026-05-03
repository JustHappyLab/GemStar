"""Tests for src.strategies.architect — mocked LLM, no live API calls."""

from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.schemas.research import ResearchTicketV1
from src.schemas.strategy import StrategyConfigV1
from src.strategies.architect import draft_strategy

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

VALID_YAML = """\
version: StrategyConfigV1
name: growth_momentum_v2
hypothesis: 增加动量因子权重以捕捉成长风格
source_idea: ticket_001
universe: chinext
timer:
  mode: full
factors:
  - factor_id: roe
    weight: 0.10
  - factor_id: revenue_yoy
    weight: 0.10
  - factor_id: netprofit_yoy
    weight: 0.10
  - factor_id: pe_inverse
    weight: 0.10
  - factor_id: pb_inverse
    weight: 0.10
  - factor_id: momentum_20d
    weight: 0.25
  - factor_id: turnover_20d
    weight: 0.10
  - factor_id: rel_strength_20d
    weight: 0.15
top_n: 5
rebalance: daily
backtest:
  start: "20220101"
  end: "20260501"
  capital: 100000.0
  rf_annual: 0.025
  volume_limit_pct: 0.25
  cost_multiplier: 1.0
"""


def _make_tickets() -> list[ResearchTicketV1]:
    return [
        ResearchTicketV1(
            ticket_id="ticket_001",
            created_date=date(2026, 5, 3),
            ticket_type="weight_rebalance",
            hypothesis="提升 momentum_20d 权重",
            rationale="牛市环境动量因子表现好",
            affected_factors=["momentum_20d"],
            confidence=0.7,
        )
    ]


def _make_pool_json(tmpdir: Path) -> Path:
    pool = {
        "version": 2,
        "last_updated": "2026-05-03",
        "active": [
            {"name": "roe", "source": "fina_indicator", "status": "active"},
            {"name": "revenue_yoy", "source": "fina_indicator", "status": "active"},
            {"name": "netprofit_yoy", "source": "fina_indicator", "status": "active"},
            {"name": "pe_inverse", "source": "market_data", "status": "active"},
            {"name": "pb_inverse", "source": "market_data", "status": "active"},
            {"name": "momentum_20d", "source": "daily.close", "status": "active"},
            {"name": "turnover_20d", "source": "daily_basic", "status": "active"},
            {"name": "rel_strength_20d", "source": "daily.close", "status": "active"},
        ],
        "watchlist": [],
        "retired": [],
        "candidates": [],
    }
    path = tmpdir / "pool.json"
    path.write_text(json.dumps(pool))
    return path


def _make_response(text: str) -> SimpleNamespace:
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDraftStrategy:
    """Core behaviour of draft_strategy()."""

    def test_valid_yaml_writes_file(self, tmp_path: Path) -> None:
        """Mock returns valid strategy YAML; verify file is written and loads."""
        pool_path = _make_pool_json(tmp_path)
        output_dir = tmp_path / "drafts"

        with patch("src.llm.client.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create.return_value = _make_response(VALID_YAML)

            from src.llm.client import LLMClient

            llm = LLMClient(api_key="test-key")
            result = draft_strategy(
                tickets=_make_tickets(),
                pool_path=pool_path,
                reference_date="2026-05-03",
                llm_client=llm,
                output_dir=output_dir,
            )

        assert result.exists()
        config = StrategyConfigV1.from_yaml(result)
        assert config.name == "growth_momentum_v2"
        assert len(config.factors) == 8

    def test_returns_path_to_written_file(self, tmp_path: Path) -> None:
        """Returned Path exists and has .yaml extension."""
        pool_path = _make_pool_json(tmp_path)
        output_dir = tmp_path / "drafts"

        with patch("src.llm.client.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create.return_value = _make_response(VALID_YAML)

            from src.llm.client import LLMClient

            llm = LLMClient(api_key="test-key")
            result = draft_strategy(
                tickets=_make_tickets(),
                pool_path=pool_path,
                reference_date="2026-05-03",
                llm_client=llm,
                output_dir=output_dir,
            )

        assert result.exists()
        assert result.suffix == ".yaml"

    def test_invalid_yaml_raises_value_error(self, tmp_path: Path) -> None:
        """Mock returns garbage; verify ValueError is raised."""
        pool_path = _make_pool_json(tmp_path)
        output_dir = tmp_path / "drafts"

        with patch("src.llm.client.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create.return_value = _make_response(
                "not: valid: strategy: yaml: at: all:\n  nonsense: ["
            )

            from src.llm.client import LLMClient

            llm = LLMClient(api_key="test-key")

            with pytest.raises(ValueError):
                draft_strategy(
                    tickets=_make_tickets(),
                    pool_path=pool_path,
                    reference_date="2026-05-03",
                    llm_client=llm,
                    output_dir=output_dir,
                )

    def test_no_tickets_still_works(self, tmp_path: Path) -> None:
        """Empty tickets list produces a valid baseline strategy."""
        pool_path = _make_pool_json(tmp_path)
        output_dir = tmp_path / "drafts"

        with patch("src.llm.client.anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create.return_value = _make_response(VALID_YAML)

            from src.llm.client import LLMClient

            llm = LLMClient(api_key="test-key")
            result = draft_strategy(
                tickets=[],
                pool_path=pool_path,
                reference_date="2026-05-03",
                llm_client=llm,
                output_dir=output_dir,
            )

        assert result.exists()
        config = StrategyConfigV1.from_yaml(result)
        assert config.name == "growth_momentum_v2"
