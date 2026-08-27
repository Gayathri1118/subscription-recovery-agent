"""Policy Engine — deterministic rules only. Plain functions, not a
framework, on purpose (spec section 6).

Four rules, checked in order. Any violation blocks (or requires approval);
no violations means the proposed strategy passes through to the safety gate.
"""
import os

from dotenv import load_dotenv

load_dotenv()

MAX_AUTOMATED_AMOUNT = float(os.getenv("MAX_AUTOMATED_AMOUNT", 5000))
MAX_RETRY_ATTEMPTS = int(os.getenv("MAX_RETRY_ATTEMPTS", 3))


def check_policy(event, proposed_strategy: str, eligible_strategies: list[str]) -> dict:
    """Run all four policy rules against one event + proposed strategy.

    `proposed_strategy` comes from the Strategy Agent (Day 3). Until that
    node exists, callers should pass a placeholder (e.g. the first eligible
    strategy) — see docs/day2_notes.md for why that's fine as a stand-in.
    """
    violations = []

    if float(event.amount) > MAX_AUTOMATED_AMOUNT:
        violations.append("AMOUNT_OVER_LIMIT")  # → requires human approval

    if event.attempt_number >= MAX_RETRY_ATTEMPTS:
        violations.append("MAX_RETRIES_EXCEEDED")  # → BLOCK, escalate

    if event.status == "recovered":
        violations.append("ALREADY_RECOVERED")  # → BLOCK, prevent duplicate charge

    if proposed_strategy not in eligible_strategies:
        violations.append("STRATEGY_NOT_ALLOWED")  # → BLOCK

    decision = "BLOCKED" if violations else "ALLOWED"
    reasoning = (
        f"Policy violations: {violations}"
        if violations
        else f"No policy violations for strategy={proposed_strategy}"
    )
    return {"decision": decision, "violations": violations, "reasoning": reasoning}
