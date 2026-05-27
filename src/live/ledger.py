"""Append-only paper trading ledger.

CALLING SPEC:
    record = build_paper_trade_record(
        account=LiveAccountStateV1,
        decision=LiveDecisionV1,
        execution_id=str,
        trade_date=str,
        fill_price=float,
        confirmed=bool,
    ) -> PaperTradeRecordV1

    append_paper_trade(path=Path, record=PaperTradeRecordV1) -> Path
    records = read_paper_trades(path=Path) -> list[PaperTradeRecordV1]

SIDE EFFECTS:
    append_paper_trade creates parent directories and appends one JSON line.
    read_paper_trades reads a local JSONL ledger file.
"""

from __future__ import annotations

from pathlib import Path

from src.schemas.live import (
    LiveAccountStateV1,
    LiveDecisionV1,
    PaperTradeRecordV1,
)


def build_paper_trade_record(
    account: LiveAccountStateV1,
    decision: LiveDecisionV1,
    execution_id: str,
    trade_date: str,
    fill_price: float,
    confirmed: bool,
) -> PaperTradeRecordV1:
    """Create an executed paper trade record from a confirmed live decision."""
    if not confirmed:
        raise ValueError("paper trade execution requires explicit confirmation")
    action = decision.intent.action
    if action not in {"buy", "add", "sell", "reduce"}:
        raise ValueError(f"decision action cannot be executed: {action}")
    shares = decision.intent.shares
    current_shares, bought_today = _position_state(account, decision.ts_code)
    if action in {"sell", "reduce"} and bought_today:
        raise ValueError("T+1 restriction: cannot sell shares bought today")

    if action in {"buy", "add"}:
        position_after = current_shares + shares
    else:
        if shares > current_shares:
            raise ValueError("cannot sell more shares than current position")
        position_after = current_shares - shares

    return PaperTradeRecordV1(
        execution_id=execution_id,
        decision_id=decision.decision_id,
        created_at=decision.created_at,
        trade_date=trade_date,
        strategy_name=decision.strategy_name,
        ts_code=decision.ts_code,
        action=action,
        shares=shares,
        fill_price=fill_price,
        confirmed=True,
        executed=True,
        position_after_shares=position_after,
    )


def append_paper_trade(path: str | Path, record: PaperTradeRecordV1) -> Path:
    """Append one paper trade, rejecting duplicate execution ids."""
    p = Path(path)
    existing_ids = {r.execution_id for r in read_paper_trades(p)}
    if record.execution_id in existing_ids:
        raise ValueError(f"duplicate execution_id: {record.execution_id}")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(record.model_dump_json() + "\n")
    return p


def read_paper_trades(path: str | Path) -> list[PaperTradeRecordV1]:
    """Read all paper trades from a JSONL ledger."""
    p = Path(path)
    if not p.exists():
        return []
    records: list[PaperTradeRecordV1] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        records.append(PaperTradeRecordV1.model_validate_json(line))
    return records


def _position_state(account: LiveAccountStateV1, ts_code: str) -> tuple[int, bool]:
    for position in account.positions:
        if position.ts_code == ts_code:
            return position.shares, position.bought_today
    return 0, False
