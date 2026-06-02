"""FactorMiner — discover, validate, and register new alpha factors.

CALLING SPEC:
    proposals = mine_factors(
        existing_pool: FactorPoolV1,
        raw_fields: list[str],
        llm_client: LLMGenerate,
    ) -> list[FactorProposal]
        Builds candidate factor expressions from deterministic templates.

    result = evaluate_proposals(
        proposals: list[FactorProposal],
        df: pd.DataFrame,
        index_daily: pd.DataFrame | None,
        existing_factor_df: pd.DataFrame | None,
        ic_window: int = 60,
        min_ic_ir: float = 0.3,
        min_coverage: float = 0.6,
        max_redundancy: float = 0.85,
    ) -> list[FactorEvaluation]
        Computes each expression, runs IC analysis, applies acceptance gates.

    accepted = register_accepted(
        evaluations: list[FactorEvaluation],
        pool: FactorPoolV1,
        run_id: str,
    ) -> tuple[FactorPoolV1, list[FactorRegistryEntryV1]]
        Returns updated pool with accepted factors moved into ``candidates``.

SIDE EFFECTS:
    None. The llm_client argument is kept for pipeline compatibility.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from pydantic import BaseModel

from src.factors.engine import compute_factor_expression, validate_expression
from src.llm.adapter import LLMGenerate
from src.ranker.ic import compute_daily_rank_ic
from src.schemas.factor import FactorPoolV1, FactorRegistryEntryV1


logger = logging.getLogger(__name__)


class FactorProposal(BaseModel):
    """Raw factor proposal after template generation and validation."""

    name: str
    expression: str
    hypothesis: str
    direction: str = "positive"
    horizon: str = "1d"


@dataclass
class FactorEvaluation:
    """Result of evaluating one proposal: metrics + acceptance flag."""

    proposal: FactorProposal
    accepted: bool
    reason: str
    ic_mean: float | None = None
    ic_ir: float | None = None
    ic_positive_rate: float | None = None
    coverage: float | None = None
    max_redundancy: float | None = None
    redundant_with: str = ""


# ---------------------------------------------------------------------------
# 1. mine_factors — build deterministic proposals
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _ProposalTemplate:
    name: str
    expression: str
    hypothesis: str
    required_fields: frozenset[str]
    direction: str = "positive"
    horizon: str = "1d"


def _templates_for_fields(raw_fields: set[str]) -> list[_ProposalTemplate]:
    volume_field = _first_present(raw_fields, ("vol", "volume"))
    templates = [
        _ProposalTemplate(
            name="intraday_range_ratio_v1",
            expression="(high - low) / close",
            hypothesis="Large intraday ranges can indicate instability and weaker next-day risk-adjusted returns.",
            required_fields=frozenset({"high", "low", "close"}),
            direction="negative",
        ),
        _ProposalTemplate(
            name="close_to_range_position_v1",
            expression="(close - low) / (high - low)",
            hypothesis="Closing near the high of the daily range may capture short-term demand pressure.",
            required_fields=frozenset({"close", "high", "low"}),
            direction="positive",
        ),
        _ProposalTemplate(
            name="gap_reversal_v1",
            expression="(open - ts_delay(close, 1)) / ts_delay(close, 1)",
            hypothesis="Large opening gaps can mean-revert when liquidity is thin or news is over-discounted.",
            required_fields=frozenset({"open", "close"}),
            direction="negative",
        ),
        _ProposalTemplate(
            name="realized_volatility_20d_v1",
            expression="ts_std(ts_pct_change(close, 1), 20)",
            hypothesis="Recent realized volatility proxies risk and can separate stable trends from noisy moves.",
            required_fields=frozenset({"close"}),
            direction="negative",
        ),
        _ProposalTemplate(
            name="price_momentum_20d_v1",
            expression="ts_pct_change(close, 20)",
            hypothesis="Twenty-day price momentum captures persistent trend strength.",
            required_fields=frozenset({"close"}),
            direction="positive",
        ),
        _ProposalTemplate(
            name="pb_inverse_value_v1",
            expression="1 / pb",
            hypothesis="Lower price-to-book valuation can identify value support in broad cross-sections.",
            required_fields=frozenset({"pb"}),
            direction="positive",
        ),
        _ProposalTemplate(
            name="pe_inverse_value_v1",
            expression="1 / pe_ttm",
            hypothesis="Lower trailing earnings valuation can identify stocks with valuation support.",
            required_fields=frozenset({"pe_ttm"}),
            direction="positive",
        ),
        _ProposalTemplate(
            name="log_size_v1",
            expression="log(total_mv)",
            hypothesis="Market-cap scale helps test size effects and liquidity preference by regime.",
            required_fields=frozenset({"total_mv"}),
            direction="neutral",
        ),
        _ProposalTemplate(
            name="turnover_zscore_20d_v1",
            expression="ts_zscore(turnover_rate, 20)",
            hypothesis="Turnover surprise can capture changes in attention and participation.",
            required_fields=frozenset({"turnover_rate"}),
            direction="positive",
        ),
    ]
    if volume_field is not None:
        templates.extend(
            [
                _ProposalTemplate(
                    name=f"{volume_field}_zscore_20d_v1",
                    expression=f"ts_zscore({volume_field}, 20)",
                    hypothesis="Volume surprise can capture abrupt attention and liquidity shocks.",
                    required_fields=frozenset({volume_field}),
                    direction="positive",
                ),
                _ProposalTemplate(
                    name=f"price_{volume_field}_corr_20d_v1",
                    expression=f"ts_corr(ts_pct_change(close, 1), ts_pct_change({volume_field}, 1), 20)",
                    hypothesis="Price-volume correlation can distinguish confirmed demand from noisy trading.",
                    required_fields=frozenset({"close", volume_field}),
                    direction="positive",
                ),
                _ProposalTemplate(
                    name=f"liquidity_momentum_{volume_field}_v1",
                    expression=f"ts_pct_change(close, 20) * ts_zscore({volume_field}, 20)",
                    hypothesis="Momentum confirmed by volume surprise can identify crowded but persistent moves.",
                    required_fields=frozenset({"close", volume_field}),
                    direction="positive",
                ),
            ]
        )
    return templates


def _first_present(raw_fields: set[str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in raw_fields:
            return candidate
    return None


def mine_factors(
    existing_pool: FactorPoolV1,
    raw_fields: list[str],
    llm_client: LLMGenerate,
) -> list[FactorProposal]:
    """Build candidate factor expressions from the available raw fields."""
    _ = llm_client
    allowed_fields = set(raw_fields)
    proposals: list[FactorProposal] = []
    for template in _templates_for_fields(allowed_fields):
        if template.name in {p.name for p in proposals} or existing_pool.is_registered(template.name):
            continue
        if not template.required_fields.issubset(allowed_fields):
            continue
        try:
            validate_expression(template.expression, allowed_fields)
        except ValueError as exc:
            logger.info("Dropping template %s: %s", template.name, exc)
            continue
        proposals.append(
            FactorProposal(
                name=template.name,
                expression=template.expression,
                hypothesis=template.hypothesis,
                direction=template.direction,
                horizon=template.horizon,
            )
        )
        if len(proposals) >= 6:
            break
    return proposals


# ---------------------------------------------------------------------------
# 2. evaluate_proposals — compute, run IC, apply gates
# ---------------------------------------------------------------------------

def _compute_proposal_values(
    proposal: FactorProposal,
    df: pd.DataFrame,
    allowed_fields: set[str],
) -> pd.Series | None:
    """Compute one proposal; return None on parse/eval failure."""
    try:
        validate_expression(proposal.expression, allowed_fields)
        series = compute_factor_expression(proposal.expression, df, allowed_fields)
        return series
    except Exception as exc:
        logger.info("Proposal %s failed to compute: %s", proposal.name, exc)
        return None


def _max_abs_correlation(
    candidate: pd.Series,
    reference_df: pd.DataFrame | None,
) -> tuple[float, str]:
    """Return (max |rho|, name) against existing factor columns; (0.0, '') if none."""
    if reference_df is None or reference_df.empty:
        return 0.0, ""
    aligned = pd.concat([candidate.rename("__cand"), reference_df.reset_index(drop=True)], axis=1)
    aligned = aligned.dropna(subset=["__cand"])
    if aligned.empty:
        return 0.0, ""
    best_rho = 0.0
    best_name = ""
    for col in reference_df.columns:
        if col in {"ts_code", "trade_date"}:
            continue
        pair = aligned[["__cand", col]].dropna()
        if len(pair) < 30:
            continue
        rho = pair["__cand"].corr(pair[col])
        if pd.isna(rho):
            continue
        if abs(rho) > abs(best_rho):
            best_rho = rho
            best_name = col
    return abs(best_rho), best_name


def evaluate_proposals(
    proposals: list[FactorProposal],
    df: pd.DataFrame,
    raw_fields: set[str],
    daily_df: pd.DataFrame,
    existing_factor_df: pd.DataFrame | None = None,
    *,
    min_ic_ir: float = 0.3,
    min_coverage: float = 0.6,
    max_redundancy: float = 0.85,
) -> list[FactorEvaluation]:
    """Compute proposals, run IC, apply acceptance gates.

    Args:
        proposals: LLM proposals.
        df: Panel DataFrame with ts_code + trade_date + raw fields, sorted.
        raw_fields: Allowed field names for expressions.
        daily_df: For computing forward returns (must have ts_code, trade_date, close).
        existing_factor_df: Optional panel of existing factor values for redundancy check.
        min_ic_ir: Minimum |IC_IR| to accept.
        min_coverage: Minimum coverage (non-NaN ratio) to accept.
        max_redundancy: Max |correlation| with any existing factor.

    Returns:
        One FactorEvaluation per proposal.
    """
    if not proposals:
        return []

    # Compute all proposal series at once into a panel-aligned DataFrame.
    panel = df[["ts_code", "trade_date"]].copy().reset_index(drop=True)
    panel_factors: dict[str, pd.Series] = {}
    computation_errors: dict[str, str] = {}
    for p in proposals:
        series = _compute_proposal_values(p, df, raw_fields)
        if series is None:
            computation_errors[p.name] = "expression failed to compute"
            continue
        # Reset index to align with panel
        panel_factors[p.name] = series.reset_index(drop=True)

    if not panel_factors:
        return [
            FactorEvaluation(
                proposal=p,
                accepted=False,
                reason=computation_errors.get(p.name, "no computation"),
            )
            for p in proposals
        ]

    factor_df = pd.concat([panel] + [s.rename(name) for name, s in panel_factors.items()], axis=1)

    # IC analysis on next-day returns
    ic_df = compute_daily_rank_ic(factor_df, daily_df, list(panel_factors.keys()))

    evaluations: list[FactorEvaluation] = []
    for p in proposals:
        if p.name not in panel_factors:
            evaluations.append(FactorEvaluation(
                proposal=p,
                accepted=False,
                reason=computation_errors.get(p.name, "no computation"),
            ))
            continue

        series = panel_factors[p.name]
        coverage = float(series.notna().mean())

        # IC stats
        if p.name in ic_df.columns:
            ic_series = ic_df[p.name].dropna()
            if len(ic_series) >= 5 and ic_series.std() > 0:
                ic_mean = float(ic_series.mean())
                ic_std = float(ic_series.std())
                ic_ir = ic_mean / ic_std
                ic_positive_rate = float((ic_series > 0).mean())
            else:
                ic_mean = ic_ir = ic_positive_rate = None
        else:
            ic_mean = ic_ir = ic_positive_rate = None

        effective_ir = _directional_effective_ir(ic_ir, p.direction)

        # Redundancy vs existing factors
        max_redund, redund_name = _max_abs_correlation(series, existing_factor_df)

        reasons: list[str] = []
        if coverage < min_coverage:
            reasons.append(f"coverage {coverage:.2f} < {min_coverage}")
        if effective_ir is None:
            reasons.append("IC_IR not computable")
        elif effective_ir < min_ic_ir:
            reasons.append(f"directional IC_IR {effective_ir:.2f} < {min_ic_ir}")
        if max_redund > max_redundancy:
            reasons.append(f"redundant (rho={max_redund:.2f} with {redund_name})")

        accepted = len(reasons) == 0
        evaluations.append(FactorEvaluation(
            proposal=p,
            accepted=accepted,
            reason="; ".join(reasons) if reasons else "passed all gates",
            ic_mean=ic_mean,
            ic_ir=ic_ir,
            ic_positive_rate=ic_positive_rate,
            coverage=coverage,
            max_redundancy=max_redund,
            redundant_with=redund_name,
        ))
    return evaluations


def _directional_effective_ir(ic_ir: float | None, direction: str) -> float | None:
    if ic_ir is None:
        return None
    if direction == "negative":
        return -ic_ir
    if direction == "neutral":
        return abs(ic_ir)
    return ic_ir


# ---------------------------------------------------------------------------
# 3. register_accepted — write to FactorPoolV1.candidates
# ---------------------------------------------------------------------------

def register_accepted(
    evaluations: list[FactorEvaluation],
    pool: FactorPoolV1,
    run_id: str,
) -> tuple[FactorPoolV1, list[FactorRegistryEntryV1]]:
    """Move accepted proposals into pool.candidates; return updated pool + new entries."""
    today = date.today().isoformat()
    new_entries: list[FactorRegistryEntryV1] = []

    # Build a copy of the pool with accepted proposals appended
    updated = pool.model_copy(deep=True)

    for ev in evaluations:
        if not ev.accepted:
            continue
        if updated.is_registered(ev.proposal.name):
            continue
        entry = FactorRegistryEntryV1(
            name=ev.proposal.name,
            source="factor_miner",
            computation=ev.proposal.expression,
            expression=ev.proposal.expression,
            hypothesis=ev.proposal.hypothesis,
            ic_mean=ev.ic_mean,
            ic_ir=ev.ic_ir,
            ic_positive_rate=ev.ic_positive_rate,
            coverage=ev.coverage,
            direction=ev.proposal.direction,
            horizon=ev.proposal.horizon,
            universe="a_share_core",
            last_updated=today,
            discovered_in_run=run_id,
            status="candidate",
        )
        updated.candidates.append(entry)
        new_entries.append(entry)

    if new_entries:
        updated.last_updated = today
    return updated, new_entries
