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


_ACTION_LABELS = {
    "buy": "买入",
    "sell": "卖出",
    "add": "加仓",
    "reduce": "减仓",
    "hold": "持有",
    "blocked": "受限",
}

_ACTION_VERBS = {
    "buy": "建议买入",
    "sell": "建议卖出",
    "add": "建议加仓",
    "reduce": "建议减仓",
    "hold": "建议持有",
    "blocked": "暂不执行",
}

_RISK_LABELS = {
    "missing_snapshot": "缺少实时行情",
    "stale_snapshot": "行情日期过期",
    "min_trade_value": "低于最低交易金额",
    "limit_up": "涨停，无法追买",
    "limit_down": "跌停，无法卖出",
}


def notification_from_decision(
    decision: LiveDecisionV1,
    symbol_names: dict[str, str] | None = None,
) -> NotificationMessageV1:
    """Build the canonical user-facing notification for a live decision."""
    action = decision.intent.action
    shares = decision.intent.shares
    price = decision.intent.reference_price
    price_text = "n/a" if price is None else f"{price:.2f}"
    label = _ACTION_LABELS.get(action, action)
    risk_text = _risk_text(decision.intent.risk_flags)
    symbol_text = format_symbol_label(decision.ts_code, symbol_names)
    action_text = _action_text(action, shares)
    status_text = _status_text(action)
    amount_text = _amount_text(shares, price)
    reason_text = _reason_text(decision.intent.reason)
    return NotificationMessageV1(
        message_id=f"notify-{decision.decision_id}",
        created_at=decision.created_at,
        severity=decision.severity,
        title=f"[{label}] {symbol_text}",
        body=(
            f"结论：{action_text}（{status_text}）\n"
            f"标的：{symbol_text}\n"
            f"策略：{decision.strategy_name}\n"
            f"操作：{action_text}\n"
            f"参考价：{price_text}\n"
            f"估算金额：{amount_text}\n"
            f"理由：{reason_text}\n"
            f"风险/限制：{risk_text}"
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
        return "受限，不能下单"
    if action == "hold":
        return "无需操作"
    return "可执行"


def _action_text(action: str, shares: int) -> str:
    verb = _ACTION_VERBS.get(action, action)
    if shares > 0:
        return f"{verb} {shares} 股"
    return verb


def _amount_text(shares: int, price: float | None) -> str:
    if shares <= 0 or price is None:
        return "n/a"
    return f"{shares * price:,.2f}"


def _risk_text(risk_flags: list[str]) -> str:
    if not risk_flags:
        return "无"
    return "、".join(_RISK_LABELS.get(flag, flag) for flag in risk_flags)


def _reason_text(reason: str) -> str:
    if not reason:
        return "未提供"

    base, sep, detail = reason.partition(":")
    base_text = {
        "target shares exceed current shares": "目标股数高于当前持仓",
        "target shares are below current shares": "目标股数低于当前持仓",
        "target is within one trading lot of current position": "目标仓位与当前持仓差异不足一手",
        "trade value is below live minimum threshold": "估算交易金额低于实时提醒最低门槛",
        "buy blocked because the stock is limit-up": "买入受限：标的涨停",
        "sell blocked because the stock is limit-down": "卖出受限：标的跌停",
        "missing market snapshot": "缺少实时行情，无法判断是否可交易",
        "stale market snapshot": "行情日期过期，暂停可执行交易提醒",
    }.get(base.strip(), base.strip())
    if not sep:
        return base_text

    detail_text = _detail_reason_text(detail.strip())
    if detail_text:
        return f"{base_text}；策略原因：{detail_text}"
    return base_text


def _detail_reason_text(detail: str) -> str:
    if not detail:
        return ""
    if detail == "top ranked":
        return "入选策略排名靠前"
    if detail.startswith("top from "):
        return detail.replace("top from ", "来自策略 ").replace(" (rank #", "，排名 #").replace(")", "")
    return detail
