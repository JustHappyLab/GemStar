"""Tests for src.strategies.architect — mocked LLM, no live API calls."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from src.schemas.research import ResearchTicketV1
from src.schemas.strategy import StrategyConfigV1
from src.strategies.architect import draft_strategy
from tests.llm_fakes import FakeLLM

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

FENCED_NEW_FACTOR_YAML = """\
```yaml
version: StrategyConfigV1
name: low_vol_proxy
hypothesis: Use active factors as a proxy because volatility_20d is not in the pool
source_idea: ticket_20260506_003 requested volatility_20d; proxy with existing factors
universe: gemstar_default
timer:
  mode: full
factors:
  - factor_id: volatility_20d
    weight: 0.30
  - factor_id: turnover_20d
    weight: -0.10
  - factor_id: roe
    weight: 0.40
  - factor_id: rel_strength_20d
    weight: 0.20
top_n: 5
rebalance: daily
backtest:
  start: "20220101"
  end: "20260506"
  capital: 100000.0
  rf_annual: 0.025
  volume_limit_pct: 0.25
  cost_multiplier: 1.0
```
"""

PROSE_WRAPPED_COLON_YAML = """\
Here is the executable draft:

version: StrategyConfigV1
name: momentum_colon_text
hypothesis: weight_rebalance (confidence: 0.72) uses momentum tilt
source_idea: ticket_20260506_001: momentum_20d up, turnover_20d down
universe: auto
universe_rationale: no board-specific mandate: use auto
timer:
  mode: full
factors:
  - factor_id: momentum_20d
    weight: 0.6
  - factor_id: roe
    weight: 0.4
top_n: 5
rebalance: daily
backtest:
  start: "20220101"
  end: "20260506"
  capital: 100000.0
  rf_annual: 0.025
  volume_limit_pct: 0.25
  cost_multiplier: 1.0
"""

MARKDOWN_FACTOR_LIST = """\
- `vol_price_corr_v1`（量价相关性，IC_IR=-0.47）
- `historical_volatility_20d_v1`（低波动代理）
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDraftStrategy:
    """Core behaviour of draft_strategy()."""

    def test_valid_yaml_writes_file(self, tmp_path: Path) -> None:
        """Mock returns valid strategy YAML; verify file is written and loads."""
        pool_path = _make_pool_json(tmp_path)
        output_dir = tmp_path / "drafts"

        result = draft_strategy(
            tickets=_make_tickets(),
            pool_path=pool_path,
            reference_date="2026-05-03",
            llm_client=FakeLLM(VALID_YAML),
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

        result = draft_strategy(
            tickets=_make_tickets(),
            pool_path=pool_path,
            reference_date="2026-05-03",
            llm_client=FakeLLM(VALID_YAML),
            output_dir=output_dir,
        )

        assert result.exists()
        assert result.suffix == ".yaml"

    def test_invalid_yaml_raises_value_error(self, tmp_path: Path) -> None:
        """Mock returns garbage; verify ValueError is raised."""
        pool_path = _make_pool_json(tmp_path)
        output_dir = tmp_path / "drafts"
        llm = FakeLLM("not: valid: strategy: yaml: at: all:\n  nonsense: [")

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

        result = draft_strategy(
            tickets=[],
            pool_path=pool_path,
            reference_date="2026-05-03",
            llm_client=FakeLLM(VALID_YAML),
            output_dir=output_dir,
        )

        assert result.exists()
        config = StrategyConfigV1.from_yaml(result)
        assert config.name == "growth_momentum_v2"

    def test_new_factor_draft_is_normalized_to_active_positive_factors(self, tmp_path: Path) -> None:
        """Unavailable and negative-weight factors are removed before schema validation."""
        pool_path = _make_pool_json(tmp_path)
        output_dir = tmp_path / "drafts"

        result = draft_strategy(
            tickets=_make_tickets(),
            pool_path=pool_path,
            reference_date="2026-05-06",
            llm_client=FakeLLM(FENCED_NEW_FACTOR_YAML),
            output_dir=output_dir,
        )

        config = StrategyConfigV1.from_yaml(result)
        factor_ids = [factor.factor_id for factor in config.factors]
        assert config.universe == "auto"
        assert factor_ids == ["roe", "rel_strength_20d"]
        assert sum(factor.weight for factor in config.factors) == pytest.approx(1.0)

    def test_no_usable_active_factors_raises_value_error(self, tmp_path: Path) -> None:
        """Drafts with only unknown or non-positive factors fail with a clear error."""
        pool_path = _make_pool_json(tmp_path)
        output_dir = tmp_path / "drafts"
        bad_yaml = """\
version: StrategyConfigV1
name: impossible_low_vol
factors:
  - factor_id: volatility_20d
    weight: 1.0
"""
        llm = FakeLLM(bad_yaml)

        with pytest.raises(ValueError, match="no usable positive-weight factors"):
            draft_strategy(
                tickets=_make_tickets(),
                pool_path=pool_path,
                reference_date="2026-05-06",
                llm_client=llm,
                output_dir=output_dir,
            )

    def test_prose_wrapped_colon_text_yaml_is_parsed(self, tmp_path: Path) -> None:
        """Common CLI-provider prose and colon text still produce a valid draft."""
        pool_path = _make_pool_json(tmp_path)
        output_dir = tmp_path / "drafts"

        result = draft_strategy(
            tickets=_make_tickets(),
            pool_path=pool_path,
            reference_date="2026-05-06",
            llm_client=FakeLLM(PROSE_WRAPPED_COLON_YAML),
            output_dir=output_dir,
        )

        config = StrategyConfigV1.from_yaml(result)
        assert config.name == "momentum_colon_text"
        assert "confidence: 0.72" in config.hypothesis
        assert "ticket_20260506_001:" in config.source_idea

    def test_invalid_markdown_list_is_repaired_once(self, tmp_path: Path) -> None:
        """A prose factor list triggers one repair request before failing the ticket."""
        pool_path = _make_pool_json(tmp_path)
        output_dir = tmp_path / "drafts"
        llm = FakeLLM([MARKDOWN_FACTOR_LIST, VALID_YAML])

        result = draft_strategy(
            tickets=_make_tickets(),
            pool_path=pool_path,
            reference_date="2026-05-03",
            llm_client=llm,
            output_dir=output_dir,
        )

        config = StrategyConfigV1.from_yaml(result)
        assert config.name == "growth_momentum_v2"
        assert len(llm.calls) == 2
        assert "Previous strategy draft was rejected" in llm.calls[1]["prompt"]
        assert "version: StrategyConfigV1" in llm.calls[1]["prompt"]
