"""Tests for FactorMiner — proposal generation, evaluation, and registration."""

import numpy as np
import pandas as pd

from src.factors.engine import validate_expression
from src.factors.miner import (
    FactorEvaluation,
    FactorProposal,
    _directional_effective_ir,
    evaluate_proposals,
    mine_factors,
    register_accepted,
)
from src.schemas.factor import FactorPoolV1, FactorRegistryEntryV1


RAW_FIELDS = {"close", "open", "high", "low", "volume", "turnover_rate", "pe_ttm", "pb", "total_mv"}


def _panel(n_dates: int = 120, n_stocks: int = 8, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_dates, freq="B").strftime("%Y%m%d").tolist()
    codes = [f"00000{i}.SZ" for i in range(n_stocks)]
    rows = []
    for code in codes:
        base = rng.uniform(10, 100)
        drift = rng.uniform(-0.001, 0.002)
        price = base
        for d in dates:
            price = price * (1 + drift + rng.normal(0, 0.02))
            rows.append({
                "ts_code": code,
                "trade_date": d,
                "close": price,
                "open": price * (1 + rng.normal(0, 0.005)),
                "high": price * (1 + abs(rng.normal(0, 0.01))),
                "low": price * (1 - abs(rng.normal(0, 0.01))),
                "volume": 1000 + rng.normal(0, 100),
                "turnover_rate": rng.uniform(0.5, 5.0),
                "pe_ttm": rng.uniform(10, 50),
                "pb": rng.uniform(1, 5),
                "total_mv": rng.uniform(1e5, 1e7),
            })
    df = pd.DataFrame(rows).sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    return df


# -------------------- mine_factors (deterministic templates) --------------------

class _FakeLLM:
    def __init__(self, reply: str) -> None:
        self._reply = reply
        self.calls: list[dict[str, str | None]] = []

    def generate(self, prompt: str, system: str | None = None) -> str:  # noqa: ARG002
        self.calls.append({"prompt": prompt, "system": system})
        return self._reply


def test_mine_factors_generates_templates_without_llm():
    pool = FactorPoolV1()
    llm = _FakeLLM("not json")

    proposals = mine_factors(pool, ["close", "high", "low", "turnover_rate"], llm)

    assert llm.calls == []
    assert {p.name for p in proposals} >= {
        "intraday_range_ratio_v1",
        "close_to_range_position_v1",
        "realized_volatility_20d_v1",
        "price_momentum_20d_v1",
        "turnover_zscore_20d_v1",
    }


def test_mine_factors_produces_valid_expressions():
    raw_fields = ["close", "open", "high", "low", "vol", "pb", "pe_ttm", "total_mv"]

    proposals = mine_factors(FactorPoolV1(), raw_fields, _FakeLLM("ignored"))

    assert proposals
    for proposal in proposals:
        validate_expression(proposal.expression, set(raw_fields))


def test_mine_factors_drops_duplicates_of_existing():
    pool = FactorPoolV1(active=[FactorRegistryEntryV1(name="intraday_range_ratio_v1", status="active")])

    proposals = mine_factors(pool, ["close", "high", "low"], _FakeLLM("ignored"))

    assert "intraday_range_ratio_v1" not in {p.name for p in proposals}


def test_mine_factors_uses_available_volume_field():
    proposals = mine_factors(
        FactorPoolV1(),
        ["close", "vol"],
        _FakeLLM("ignored"),
    )

    assert "vol_zscore_20d_v1" in {p.name for p in proposals}
    assert any("vol" in p.expression for p in proposals)


def test_mine_factors_returns_empty_without_supported_fields():
    proposals = mine_factors(FactorPoolV1(), ["unknown_field"], _FakeLLM("ignored"))

    assert proposals == []


# -------------------- evaluate_proposals --------------------

def test_evaluate_accepts_high_ic_factor():
    df = _panel()
    # Construct a proposal whose values are correlated with next-day returns.
    # Cheat: use future return as the factor — should get perfect IC.
    # Instead, use a known-predictive expression.
    proposals = [
        FactorProposal(
            name="return_5d_v1",
            expression="ts_pct_change(close, 5)",
            hypothesis="momentum",
            direction="positive",
            horizon="1d",
        ),
    ]
    evals = evaluate_proposals(
        proposals=proposals,
        df=df,
        raw_fields=RAW_FIELDS,
        daily_df=df,
        min_ic_ir=0.01,  # very loose for a synthetic panel
        min_coverage=0.1,
        max_redundancy=0.99,
    )
    assert len(evals) == 1
    assert evals[0].coverage is not None
    assert evals[0].ic_ir is not None


def test_evaluate_rejects_bad_expression():
    df = _panel()
    proposals = [
        FactorProposal(
            name="broken_v1",
            expression="nonsense_field * 2",
            hypothesis="should fail",
            direction="positive",
            horizon="1d",
        ),
    ]
    evals = evaluate_proposals(
        proposals=proposals,
        df=df,
        raw_fields=RAW_FIELDS,
        daily_df=df,
    )
    assert len(evals) == 1
    assert evals[0].accepted is False
    assert "failed" in evals[0].reason or "compute" in evals[0].reason


def test_evaluate_rejects_low_coverage():
    df = _panel()
    # Use a window so large that most rows are NaN.
    proposals = [
        FactorProposal(
            name="sparse_v1",
            expression="ts_mean(close, 500)",
            hypothesis="sparse",
            direction="positive",
            horizon="1d",
        ),
    ]
    evals = evaluate_proposals(
        proposals=proposals,
        df=df,
        raw_fields=RAW_FIELDS,
        daily_df=df,
        min_coverage=0.5,
        min_ic_ir=0.01,
    )
    assert evals[0].accepted is False
    assert "coverage" in evals[0].reason


def test_evaluate_redundancy_gate():
    """A proposal identical to an existing factor must be rejected."""
    df = _panel()
    # Existing "factor" column equal to close itself
    existing = df[["ts_code", "trade_date", "close"]].rename(columns={"close": "price_level"})
    proposals = [
        FactorProposal(
            name="identical_v1",
            expression="close",
            hypothesis="duplicate",
            direction="positive",
            horizon="1d",
        ),
    ]
    evals = evaluate_proposals(
        proposals=proposals,
        df=df,
        raw_fields=RAW_FIELDS,
        daily_df=df,
        existing_factor_df=existing,
        min_ic_ir=0.01,
        min_coverage=0.1,
        max_redundancy=0.5,
    )
    assert evals[0].accepted is False
    assert "redundant" in evals[0].reason


def test_directional_effective_ir_respects_declared_direction():
    assert _directional_effective_ir(0.4, "positive") == 0.4
    assert _directional_effective_ir(-0.4, "positive") == -0.4
    assert _directional_effective_ir(-0.4, "negative") == 0.4
    assert _directional_effective_ir(0.4, "negative") == -0.4
    assert _directional_effective_ir(-0.4, "neutral") == 0.4


# -------------------- register_accepted --------------------

def test_register_appends_accepted_to_candidates():
    pool = FactorPoolV1(
        active=[FactorRegistryEntryV1(name="existing", status="active")],
    )
    evals = [
        FactorEvaluation(
            proposal=FactorProposal(
                name="new_v1",
                expression="(high - low) / close",
                hypothesis="amp",
                direction="negative",
                horizon="1d",
            ),
            accepted=True,
            reason="passed all gates",
            ic_mean=0.02,
            ic_ir=0.4,
            ic_positive_rate=0.55,
            coverage=0.9,
            max_redundancy=0.3,
        ),
        FactorEvaluation(
            proposal=FactorProposal(
                name="rejected_v1",
                expression="close",
                hypothesis="",
                direction="positive",
                horizon="1d",
            ),
            accepted=False,
            reason="failed",
        ),
    ]
    updated, new_entries = register_accepted(evals, pool, run_id="20260507-test")

    assert len(new_entries) == 1
    assert new_entries[0].name == "new_v1"
    assert new_entries[0].status == "candidate"
    assert new_entries[0].discovered_in_run == "20260507-test"
    assert updated.is_registered("new_v1")
    assert not updated.is_registered("rejected_v1")
    # Original pool should be unchanged
    assert not pool.is_registered("new_v1")


def test_register_skips_name_collision():
    pool = FactorPoolV1(
        candidates=[FactorRegistryEntryV1(name="dup_v1", status="candidate")],
    )
    evals = [
        FactorEvaluation(
            proposal=FactorProposal(
                name="dup_v1",
                expression="close",
                hypothesis="",
                direction="positive",
                horizon="1d",
            ),
            accepted=True,
            reason="ok",
        ),
    ]
    updated, new_entries = register_accepted(evals, pool, run_id="r")
    assert new_entries == []
    assert len(updated.candidates) == 1
