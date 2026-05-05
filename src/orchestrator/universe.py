"""Universe preset resolution and candidate filtering helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from src.schemas.strategy import StrategyConfigV1


@dataclass(frozen=True)
class UniverseResolution:
    requested: str
    resolved: str
    reason: str
    filters: tuple[str, ...]

    def model_dump(self) -> dict:
        return asdict(self)


_A_SHARE_PREFIX = r"^(00[0-3]|30[01]|60[0-9]|68[89]|4[0-9]|8[0-9]|920)"
_CHINEXT_PREFIX = r"^30[01]"
_STAR_PREFIX = r"^68[89]"
_MAIN_BOARD_PREFIX = r"^(00[0-3]|60[0-9])"
_CORE_MIN_LIST_DAYS = 120


def resolve_strategy_universe(strategy: StrategyConfigV1) -> UniverseResolution:
    requested_raw = (strategy.universe or "auto").strip().lower()
    requested = _normalize_requested(requested_raw)
    if requested != "auto":
        return _resolution_for(
            requested,
            strategy.universe_rationale or "Strategy explicitly requested this universe.",
            requested=requested_raw,
        )

    text = " ".join([
        strategy.name,
        strategy.hypothesis,
        strategy.source_idea,
        " ".join(f.factor_id for f in strategy.factors),
    ]).lower()

    if _contains_any(text, ("创业板", "chinext", "300", "301")):
        return _with_strategy_rationale(_resolution_for(
            "chinext_core",
            "Auto-selected because the strategy context points to ChiNext / growth-board exposure.",
            requested="auto",
        ), strategy.universe_rationale)
    if _contains_any(text, ("科创", "科创板", "star", "688", "硬科技", "semiconductor")):
        return _with_strategy_rationale(_resolution_for(
            "star_core",
            "Auto-selected because the strategy context points to STAR Market / hard-tech exposure.",
            requested="auto",
        ), strategy.universe_rationale)
    if _contains_any(text, ("主板", "main board", "高股息", "防御")):
        return _with_strategy_rationale(_resolution_for(
            "main_board_core",
            "Auto-selected because the strategy context points to main-board defensive exposure.",
            requested="auto",
        ), strategy.universe_rationale)
    if _contains_any(text, ("短线", "高流动", "流动性", "liquid")):
        return _with_strategy_rationale(_resolution_for(
            "a_share_liquid",
            "Auto-selected because the strategy context emphasizes liquidity or short-horizon trading.",
            requested="auto",
        ), strategy.universe_rationale)
    return _with_strategy_rationale(_resolution_for(
        "a_share_core",
        "Auto-selected default for general A-share research: broad enough to explore, filtered enough to avoid obvious tradability noise.",
        requested="auto",
    ), strategy.universe_rationale)


def resolve_universe_value(universe: str | UniverseResolution) -> UniverseResolution:
    if isinstance(universe, UniverseResolution):
        return universe
    requested_raw = (universe or "auto").strip().lower()
    requested = _normalize_requested(requested_raw)
    if requested == "auto":
        return _resolution_for(
            "a_share_core",
            "Auto-selected default for general A-share research.",
            requested="auto",
        )
    return _resolution_for(
        requested,
        "Strategy explicitly requested this universe.",
        requested=requested_raw,
    )


def filter_group_for_universe(
    group: pd.DataFrame,
    *,
    stock_basic: pd.DataFrame | None,
    trade_date: str,
    resolution: UniverseResolution,
) -> pd.DataFrame:
    """Filter one trade-date cross-section according to a resolved universe."""
    if group.empty:
        return group

    filtered = group.copy()
    eligible = eligible_codes_from_stock_basic(stock_basic, trade_date, resolution)
    if eligible is not None:
        filtered = filtered[filtered["ts_code"].astype(str).isin(eligible)]
    else:
        filtered = _filter_by_prefix(filtered, resolution.resolved)

    if filtered.empty:
        return filtered

    if resolution.resolved.endswith("_liquid") and "amount" in filtered.columns:
        amount = pd.to_numeric(filtered["amount"], errors="coerce")
        positive = filtered[amount > 0]
        if len(positive) > 1:
            threshold = pd.to_numeric(positive["amount"], errors="coerce").quantile(0.2)
            filtered = positive[pd.to_numeric(positive["amount"], errors="coerce") >= threshold]

    return filtered


def eligible_codes_from_stock_basic(
    stock_basic: pd.DataFrame | None,
    trade_date: str,
    resolution: UniverseResolution,
) -> set[str] | None:
    if stock_basic is None or stock_basic.empty or "ts_code" not in stock_basic.columns:
        return None

    stocks = stock_basic.copy()
    if _looks_like_chinext_only(stocks) and _base_universe(resolution.resolved) in {"a_share", "main_board", "star"}:
        return None

    stocks = _filter_by_prefix(stocks, resolution.resolved)
    if "name" in stocks.columns:
        stocks = stocks[~stocks["name"].astype(str).str.contains("ST", case=False, na=False)]

    td = pd.to_datetime(trade_date, format="%Y%m%d", errors="coerce")
    if "list_date" in stocks.columns:
        listed = pd.to_datetime(stocks["list_date"], format="%Y%m%d", errors="coerce")
        listed_mask = listed.notna() & (listed <= td)
        if resolution.resolved.endswith("_core"):
            listed_mask &= (td - listed).dt.days >= _CORE_MIN_LIST_DAYS
        stocks = stocks[listed_mask]
    if "delist_date" in stocks.columns:
        delisted = pd.to_datetime(
            stocks["delist_date"].replace("", pd.NA),
            format="%Y%m%d",
            errors="coerce",
        )
        stocks = stocks[delisted.isna() | (delisted >= td)]

    return set(stocks["ts_code"].astype(str))


def describe_resolution(strategy_name: str, resolution: UniverseResolution) -> str:
    filters = "; ".join(resolution.filters)
    return (
        f"{strategy_name}: {resolution.resolved} "
        f"(requested: {resolution.requested}) - {resolution.reason} "
        f"Filters: {filters}."
    )


def _normalize_requested(universe: str | None) -> str:
    value = (universe or "auto").strip().lower()
    if value == "all":
        return "a_share"
    return value


def _resolution_for(resolved: str, reason: str, requested: str | None = None) -> UniverseResolution:
    resolved = _normalize_requested(resolved)
    requested = requested or resolved
    return UniverseResolution(
        requested=requested,
        resolved=resolved,
        reason=reason,
        filters=_filters_for(resolved),
    )


def _with_strategy_rationale(
    resolution: UniverseResolution,
    rationale: str,
) -> UniverseResolution:
    if not rationale:
        return resolution
    return UniverseResolution(
        requested=resolution.requested,
        resolved=resolution.resolved,
        reason=f"{resolution.reason} Strategy rationale: {rationale}",
        filters=resolution.filters,
    )


def _filters_for(universe: str) -> tuple[str, ...]:
    base = _base_universe(universe)
    filters = {
        "a_share": ["A-share ordinary stock code range"],
        "chinext": ["ChiNext 300/301 code range"],
        "star": ["STAR Market 688/689 code range"],
        "main_board": ["Shanghai/Shenzhen main-board 000/001/002/003/60x code range"],
    }.get(base, ["A-share ordinary stock code range"])
    filters.extend(["exclude ST names", "PIT list/delist-date eligibility"])
    if universe.endswith("_core"):
        filters.append(f"listed at least {_CORE_MIN_LIST_DAYS} calendar days")
    if universe.endswith("_liquid"):
        filters.append("exclude the lowest 20% amount names on each ranking date")
    return tuple(filters)


def _filter_by_prefix(df: pd.DataFrame, universe: str) -> pd.DataFrame:
    if "ts_code" not in df.columns:
        return df
    pattern = {
        "a_share": _A_SHARE_PREFIX,
        "chinext": _CHINEXT_PREFIX,
        "star": _STAR_PREFIX,
        "main_board": _MAIN_BOARD_PREFIX,
    }.get(_base_universe(universe), _A_SHARE_PREFIX)
    return df[df["ts_code"].astype(str).str.match(pattern)]


def _base_universe(universe: str) -> str:
    if universe.startswith("chinext"):
        return "chinext"
    if universe.startswith("star"):
        return "star"
    if universe.startswith("main_board"):
        return "main_board"
    return "a_share"


def _looks_like_chinext_only(stock_basic: pd.DataFrame) -> bool:
    codes = stock_basic["ts_code"].astype(str)
    return len(codes) > 0 and codes.str.match(_CHINEXT_PREFIX).all()


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)
