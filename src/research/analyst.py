"""ResearchAnalyst — generates deterministic research tickets.

CALLING SPEC:
    generate_tickets(regime, events, factor_health, pool_path, llm_client) -> list[ResearchTicketV1]

SIDE EFFECTS:
    None. The llm_client argument is kept for pipeline compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.llm.adapter import LLMGenerate
from src.schemas.factor import FactorHealthReportV1, FactorPoolV1
from src.schemas.research import ResearchTicketV1
from src.schemas.signal import MarketRegimeV1, SignalEventV1

_MAX_TICKETS = 5


@dataclass(frozen=True)
class _TicketCandidate:
    ticket_type: str
    hypothesis: str
    rationale: str
    affected_factors: list[str]
    affected_sectors: list[str]
    confidence: float
    source_events: list[str]


def generate_tickets(
    regime: MarketRegimeV1,
    events: list[SignalEventV1],
    factor_health: FactorHealthReportV1 | None,
    pool_path: Path,
    llm_client: LLMGenerate,
) -> list[ResearchTicketV1]:
    """Generate validated research tickets from structured market context.

    The llm_client parameter is intentionally unused. Earlier versions asked an
    LLM to produce ticket JSON directly; the pipeline now owns the structured
    contract locally so malformed model output cannot break ticket generation.
    """
    _ = llm_client
    pool = FactorPoolV1.load(pool_path)
    registered = {entry.name for entry in pool.all_entries()}

    candidates: list[_TicketCandidate] = []
    candidates.extend(_tickets_from_events(regime, events, registered))
    if factor_health is not None:
        candidates.extend(_tickets_from_factor_health(regime, factor_health, registered))

    deduped = _dedupe_candidates(candidates)
    return _build_tickets(deduped[:_MAX_TICKETS], regime)


def _tickets_from_events(
    regime: MarketRegimeV1,
    events: list[SignalEventV1],
    registered: set[str],
) -> list[_TicketCandidate]:
    candidates: list[_TicketCandidate] = []
    for event in events:
        if event.event_type == "earnings_surprise":
            factors = _choose_factors(
                registered,
                preferred=("netprofit_yoy", "roe", "revenue_yoy", "grossprofit_margin"),
                fallback=("roe",),
            )
            if factors:
                candidates.append(
                    _TicketCandidate(
                        ticket_type="factor_tweak",
                        hypothesis=(
                            "Winsorize earnings-growth factors and cross-check them with profitability "
                            f"before using them in the {regime.regime} regime."
                        ),
                        rationale=(
                            f"{event.summary} Extreme earnings rows can dominate factor ranks and should be "
                            "validated against profitability quality before increasing exposure."
                        ),
                        affected_factors=factors,
                        affected_sectors=event.affected_sectors,
                        confidence=_event_confidence(event, 0.06),
                        source_events=[event.event_id],
                    )
                )
        elif event.event_type == "factor_drift":
            factors = _choose_factors(
                registered,
                preferred=(
                    "momentum_20d",
                    "rel_strength_20d",
                    "gap_reversal_v1",
                    "overnight_reversal_v1",
                ),
                fallback=("momentum_20d",),
            )
            if factors:
                candidates.append(
                    _TicketCandidate(
                        ticket_type="weight_rebalance",
                        hypothesis=(
                            "Reduce reliance on unstable momentum exposure and test a smaller "
                            "momentum allocation until drift normalizes."
                        ),
                        rationale=(
                            f"{event.summary} The signal suggests current price-trend factors may be "
                            "less reliable without a fresh IC check."
                        ),
                        affected_factors=factors,
                        affected_sectors=event.affected_sectors,
                        confidence=_event_confidence(event, 0.0),
                        source_events=[event.event_id],
                    )
                )
        elif event.event_type == "sentiment_shift":
            factors = _choose_factors(
                registered,
                preferred=(
                    "moneyflow_surge_v1",
                    "volume_price_corr_v1",
                    "turnover_20d",
                    "liquidity_momentum_v1",
                    "momentum_20d",
                ),
                fallback=("momentum_20d",),
            )
            if factors:
                candidates.append(
                    _TicketCandidate(
                        ticket_type="new_strategy",
                        hypothesis=(
                            "Create a liquidity-shock sleeve that only promotes high-volume names when "
                            "price confirmation is present."
                        ),
                        rationale=(
                            f"{event.summary} A volume shock can be either informed buying or noisy "
                            "crowding, so the follow-up should pair liquidity with price confirmation."
                        ),
                        affected_factors=factors,
                        affected_sectors=event.affected_sectors,
                        confidence=_event_confidence(event, -0.04),
                        source_events=[event.event_id],
                    )
                )
    return candidates


def _tickets_from_factor_health(
    regime: MarketRegimeV1,
    factor_health: FactorHealthReportV1,
    registered: set[str],
) -> list[_TicketCandidate]:
    candidates: list[_TicketCandidate] = []
    for entry in factor_health.entries:
        if entry.status not in {"degraded", "critical"}:
            continue
        if entry.factor_name not in registered:
            continue
        confidence = 0.78 if entry.status == "critical" else 0.66
        candidates.append(
            _TicketCandidate(
                ticket_type="factor_tweak",
                hypothesis=(
                    f"Demote or quarantine {entry.factor_name} while it remains "
                    f"{entry.status} in the {regime.regime} regime."
                ),
                rationale=(
                    f"{entry.factor_name} health is {entry.status} "
                    f"(IC_IR={entry.ic_ir}, IC_mean={entry.ic_mean}, coverage={entry.coverage}). "
                    "A failing factor should not keep its previous allocation without a recovery check."
                ),
                affected_factors=[entry.factor_name],
                affected_sectors=[],
                confidence=confidence,
                source_events=[],
            )
        )
    return candidates


def _choose_factors(
    registered: set[str],
    preferred: tuple[str, ...],
    fallback: tuple[str, ...] = (),
    limit: int = 4,
) -> list[str]:
    selected = [name for name in preferred if name in registered]
    if not selected:
        selected = [name for name in fallback if name in registered]
    return selected[:limit]


def _event_confidence(event: SignalEventV1, adjustment: float) -> float:
    return round(min(0.9, max(0.35, event.confidence + adjustment)), 2)


def _dedupe_candidates(candidates: list[_TicketCandidate]) -> list[_TicketCandidate]:
    seen: set[tuple[str, tuple[str, ...], tuple[str, ...]]] = set()
    deduped: list[_TicketCandidate] = []
    for candidate in candidates:
        key = (
            candidate.ticket_type,
            tuple(candidate.affected_factors),
            tuple(candidate.source_events),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _build_tickets(
    candidates: list[_TicketCandidate],
    regime: MarketRegimeV1,
) -> list[ResearchTicketV1]:
    created_date = regime.as_of_date
    date_token = created_date.strftime("%Y%m%d")
    return [
        ResearchTicketV1.model_validate(
            {
                "version": "ResearchTicketV1",
                "ticket_id": f"ticket_{date_token}_{index:03d}",
                "created_date": created_date.isoformat(),
                "ticket_type": candidate.ticket_type,
                "hypothesis": candidate.hypothesis,
                "rationale": candidate.rationale,
                "affected_factors": candidate.affected_factors,
                "affected_sectors": candidate.affected_sectors,
                "confidence": candidate.confidence,
                "source_regime": regime.regime,
                "source_events": candidate.source_events,
                "status": "draft",
            }
        )
        for index, candidate in enumerate(candidates, start=1)
    ]
