"""Write human and machine readable trade status snapshots.

CALLING SPEC:
    payload = build_trade_status_payload(...)
    write_trade_status(status_dir=Path("artifacts/current"), payload=payload)

SIDE EFFECTS:
    write_trade_status creates *status_dir* and writes trade_status.json/md.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.notify.message import format_symbol_label
from src.schemas.live import (
    LiveAccountStateV1,
    LiveDecisionV1,
    MarketSnapshotV1,
    TargetHoldingV1,
)


def build_trade_status_payload(
    *,
    ref_date: str,
    run_id: str | None,
    account: LiveAccountStateV1,
    targets: list[TargetHoldingV1],
    snapshots: list[MarketSnapshotV1],
    decisions: list[LiveDecisionV1],
    strategies: list[str],
    symbol_names: dict[str, str] | None = None,
    phase: str = "targets_ready",
) -> dict:
    """Build a serializable snapshot of current account, targets, and decisions."""
    names = symbol_names or {}
    price_map = {s.ts_code: s.last_price for s in snapshots}
    target_map = {t.ts_code: t for t in targets}
    decision_map = {d.ts_code: d for d in decisions}
    position_map = {p.ts_code: p for p in account.positions}
    symbols = sorted(set(position_map) | set(target_map) | set(decision_map))

    rows = []
    market_value = 0.0
    cost_value = 0.0
    for code in symbols:
        pos = position_map.get(code)
        target = target_map.get(code)
        decision = decision_map.get(code)
        shares = pos.shares if pos else 0
        avg_cost = pos.avg_cost if pos else 0.0
        latest_price = price_map.get(code) or (pos.last_price if pos else None)
        current_value = shares * latest_price if latest_price else (pos.market_value if pos else 0.0)
        target_shares = target.target_shares if target else 0
        target_value = target_shares * latest_price if latest_price else 0.0
        pnl = (latest_price - avg_cost) * shares if latest_price and avg_cost and shares else 0.0
        market_value += current_value
        cost_value += avg_cost * shares
        rows.append({
            "ts_code": code,
            "label": format_symbol_label(code, names),
            "shares": shares,
            "avg_cost": round(avg_cost, 4),
            "last_price": round(latest_price, 4) if latest_price else None,
            "market_value": round(current_value, 2),
            "unrealized_pnl": round(pnl, 2),
            "unrealized_pnl_pct": round(pnl / (avg_cost * shares), 4) if avg_cost and shares else None,
            "target_shares": target_shares,
            "target_value": round(target_value, 2),
            "diff_shares": target_shares - shares,
            "action": decision.intent.action if decision else "hold",
            "action_shares": decision.intent.shares if decision else 0,
            "risk_flags": decision.intent.risk_flags if decision else [],
            "reason": decision.intent.reason if decision else (target.reason if target else ""),
            "bought_today": bool(pos.bought_today) if pos else False,
        })

    invested_pct = market_value / account.total_value if account.total_value else 0.0
    return {
        "version": "TradeStatusV1",
        "phase": phase,
        "ref_date": ref_date,
        "run_id": run_id,
        "strategies": strategies,
        "account": {
            "cash": round(account.cash, 2),
            "total_value": round(account.total_value, 2),
            "market_value": round(market_value, 2),
            "cost_value": round(cost_value, 2),
            "invested_pct": round(invested_pct, 4),
            "positions_count": len(account.positions),
        },
        "rows": rows,
        "decisions_count": len(decisions),
        "notifications_count": len([d for d in decisions if d.notify]),
    }


def write_trade_status(status_dir: str | Path, payload: dict) -> tuple[Path, Path]:
    """Write trade status to trade_status.json and trade_status.md."""
    path = Path(status_dir)
    path.mkdir(parents=True, exist_ok=True)
    json_path = path / "trade_status.json"
    md_path = path / "trade_status.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(format_trade_status_markdown(payload), encoding="utf-8")
    return json_path, md_path


def format_trade_status_markdown(payload: dict) -> str:
    """Render a compact Markdown status report for humans and skill context."""
    account = payload["account"]
    lines = [
        "# GemStar Trade Status",
        "",
        f"- 日期：{payload['ref_date']}",
        f"- 阶段：{payload['phase']}",
        f"- Run ID：{payload.get('run_id') or '-'}",
        f"- 策略：{', '.join(payload.get('strategies') or []) or '-'}",
        f"- 总资产：{account['total_value']:.2f}",
        f"- 现金：{account['cash']:.2f}",
        f"- 持仓市值：{account['market_value']:.2f}",
        f"- 仓位：{account['invested_pct']:.2%}",
        "",
        "## 持仓与目标",
        "",
        "| 标的 | 当前股数 | 成本 | 最新价 | 市值 | 浮盈亏 | 目标股数 | 差额 | 动作 | 风险 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    rows = payload.get("rows") or []
    if not rows:
        lines.append("| - | 0 | - | - | 0.00 | 0.00 | 0 | 0 | hold | - |")
    for row in rows:
        risk = ", ".join(row["risk_flags"]) if row["risk_flags"] else "-"
        last_price = "-" if row["last_price"] is None else f"{row['last_price']:.4f}"
        pnl_pct = "" if row["unrealized_pnl_pct"] is None else f" ({row['unrealized_pnl_pct']:.2%})"
        lines.append(
            "| {label} | {shares} | {avg_cost:.4f} | {last_price} | "
            "{market_value:.2f} | {pnl:.2f}{pnl_pct} | {target} | {diff} | {action} | {risk} |".format(
                label=row["label"],
                shares=row["shares"],
                avg_cost=row["avg_cost"],
                last_price=last_price,
                market_value=row["market_value"],
                pnl=row["unrealized_pnl"],
                pnl_pct=pnl_pct,
                target=row["target_shares"],
                diff=row["diff_shares"],
                action=row["action"],
                risk=risk,
            )
        )
    lines.extend(["", "## 说明", "", "本文件由 `gemstar trade` 自动生成，用于人工查看、第三方 skill 读取或 IM 推送摘要。", ""])
    return "\n".join(lines)
