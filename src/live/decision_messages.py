"""Convert live decisions into notification messages.

CALLING SPEC:
    message = notification_from_decision(decision=LiveDecisionV1)

SIDE EFFECTS:
    None. The returned message can be sent by any notification sink.
"""

from __future__ import annotations

from src.notify.message import NotificationMessageV1
from src.schemas.live import LiveDecisionV1


def notification_from_decision(decision: LiveDecisionV1) -> NotificationMessageV1:
    """Build the canonical user-facing notification for a live decision."""
    action = decision.intent.action
    shares = decision.intent.shares
    price = decision.intent.reference_price
    price_text = "n/a" if price is None else f"{price:.2f}"
    action_label = {"buy": "买入", "sell": "卖出", "add": "加仓", "reduce": "减仓", "hold": "持有", "blocked": "受限"}
    label = action_label.get(action, action)
    risk_text = "、".join(decision.intent.risk_flags) if decision.intent.risk_flags else "无"
    return NotificationMessageV1(
        message_id=f"notify-{decision.decision_id}",
        created_at=decision.created_at,
        severity=decision.severity,
        title=f"[{label}] {decision.ts_code}",
        body=(
            f"策略：{decision.strategy_name} | {label} {shares} 股 {decision.ts_code}\n"
            f"参考价：{price_text} | 置信度：{decision.intent.confidence:.0%} | 风险：{risk_text}\n"
            f"理由：{decision.intent.reason}"
        ),
        decision_id=decision.decision_id,
        action=action,
        symbols=[decision.ts_code],
    )
