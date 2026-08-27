"""Diagnosis node — rule-based menu of eligible strategies per failure_type.

This is deliberately the deterministic "menu" the Day-3 Strategy Agent
(LLM) will pick from. The LLM never invents a strategy — it only ranks or
selects among what diagnosis says is valid for this failure_type. Keeping
this boundary explicit is part of the "AI judgment" scoring story: the
model makes a judgment call among constrained options, it doesn't have
free rein.
"""

STRATEGY_MENU = {
    "card_declined": ["retry_same_card", "request_alt_payment_method"],
    "expired_card": ["send_update_card_link"],
    "insufficient_funds": ["delayed_retry", "negotiate_promise_to_pay"],
    "gateway_timeout": ["immediate_retry"],
}


def diagnose(failure_type: str) -> dict:
    strategies = STRATEGY_MENU.get(failure_type, [])
    return {
        "eligible_strategies": strategies,
        "reasoning": (
            f"failure_type={failure_type} maps to {len(strategies)} eligible "
            f"strategies: {strategies}"
            if strategies
            else f"failure_type={failure_type} has no known strategy mapping"
        ),
    }
