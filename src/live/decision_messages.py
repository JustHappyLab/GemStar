"""Convert live decisions into notification messages.

CALLING SPEC:
    message = notification_from_decision(
        decision=LiveDecisionV1,
        symbol_names=dict[str, str] | None,
    )

SIDE EFFECTS:
    None. The returned message can be sent by any notification sink.
"""

from __future__ import annotations

from src.notify.message import NotificationMessageV1, format_symbol_label
from src.schemas.live import LiveDecisionV1


def notification_from_decision(
    decision: LiveDecisionV1,
    symbol_names: dict[str, str] | None = None,
) -> NotificationMessageV1:
    """Build the canonical user-facing notification for a live decision."""
    action = decision.intent.action
    shares = decision.intent.shares
    price = decision.intent.reference_price
    price_text = "n/a" if price is None else f"{price:.2f}"
    action_label = {"buy": "买入", "sell": "卖出", "add": "加仓", "reduce": "减仓", "hold": "持有", "blocked": "受限"}
    label = action_label.get(action, action)
    risk_text = "、".join(decision.intent.risk_flags) if decision.intent.risk_flags else "无"
    symbol_text = format_symbol_label(decision.ts_code, symbol_names)
    action_text = f"{label} {shares} 股" if shares > 0 else label
    status_text = _status_text(action)
    return NotificationMessageV1(
        message_id=f"notify-{decision.decision_id}",
        created_at=decision.created_at,
        severity=decision.severity,
        title=f"[{label}] {symbol_text}",
        body=(
            f"标的：{symbol_text}\n"
            f"操作：{action_text}\n"
            f"策略：{decision.strategy_name}\n"
            f"参考价：{price_text}\n"
            f"状态：{status_text}\n"
            f"风险：{risk_text}\n"
            f"理由：{decision.intent.reason}"
        ),
        decision_id=decision.decision_id,
        action=action,
        symbols=[decision.ts_code],
        symbol_names={decision.ts_code: symbol_names[decision.ts_code]}
        if symbol_names and symbol_names.get(decision.ts_code)
        else {},
    )


def _status_text(action: str) -> str:
    if action == "blocked":
        return "受限"
    if action == "hold":
        return "无需操作"
    return "可执行"
