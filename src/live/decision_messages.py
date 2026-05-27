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
    risk_text = ", ".join(decision.intent.risk_flags) if decision.intent.risk_flags else "none"
    return NotificationMessageV1(
        message_id=f"notify-{decision.decision_id}",
        created_at=decision.created_at,
        severity=decision.severity,
        title=f"{action.upper()} {decision.ts_code}",
        body=(
            f"{decision.strategy_name}: {action} {shares} shares "
            f"of {decision.ts_code} near {price_text}. "
            f"Confidence: {decision.intent.confidence:.2f}. "
            f"Risk flags: {risk_text}. "
            f"Reason: {decision.intent.reason}"
        ),
        decision_id=decision.decision_id,
        action=action,
        symbols=[decision.ts_code],
    )
