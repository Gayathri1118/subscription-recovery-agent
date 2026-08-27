"""Safety Gate — deterministic. Two responsibilities:
  1. Idempotency: never execute the same (event, attempt_number) twice.
  2. Confidence floor: strategy_agent confidence < 0.8 → auto-escalate,
     regardless of what the policy engine said.

Idempotency is checked against real rows in `agent_actions`, not an
in-memory set — this has to survive process restarts, and the audit trail
is the source of truth anyway.
"""
import hashlib

from sqlalchemy.orm import Session

from app.models import AgentAction

CONFIDENCE_THRESHOLD = 0.8


def idempotency_key(failure_event_id: str, attempt_number: int) -> str:
    raw = f"{failure_event_id}:{attempt_number}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _key_already_used(db: Session, key: str) -> bool:
    """A duplicate means: this (event, attempt_number) pair already passed
    the safety gate as ALLOWED once before. We key off the safety node's
    own ALLOWED decisions rather than the executor, since the executor
    node doesn't exist until it's wired in — and an ALLOWED safety
    decision is exactly the signal that execution was (or will be)
    attempted for this key.
    """
    existing = (
        db.query(AgentAction)
        .filter(
            AgentAction.idempotency_key == key,
            AgentAction.node == "safety",
            AgentAction.decision == "ALLOWED",
        )
        .first()
    )
    return existing is not None


def check_safety(db: Session, event, policy_result: dict, confidence: float) -> dict:
    """Final go/no-go. Assumes policy_result came from app.policy.check_policy().

    `confidence` should come from the Strategy Agent (Day 3). Until that
    node exists, callers pass a placeholder value — see the TODO below,
    which must be removed once Day 3's real confidence is wired in.
    """
    key = idempotency_key(str(event.id), event.attempt_number)

    if policy_result["decision"] == "BLOCKED":
        return {
            "decision": "BLOCKED",
            "reason": "policy_violation",
            "idempotency_key": key,
            "reasoning": f"Blocked upstream by policy: {policy_result['violations']}",
        }

    if _key_already_used(db, key):
        return {
            "decision": "BLOCKED",
            "reason": "duplicate_idempotency_key",
            "idempotency_key": key,
            "reasoning": "This (event, attempt_number) pair has already been executed.",
        }

    # TODO Day 3: replace the hardcoded confidence=1.0 placeholder at call
    # sites with the real strategy_agent.confidence output. Until then this
    # rule is provably correct but not yet exercised by real LLM uncertainty.
    if confidence < CONFIDENCE_THRESHOLD:
        return {
            "decision": "ESCALATED",
            "reason": "confidence_below_threshold",
            "idempotency_key": key,
            "reasoning": f"confidence={confidence} < {CONFIDENCE_THRESHOLD} threshold",
        }

    return {
        "decision": "ALLOWED",
        "idempotency_key": key,
        "reasoning": "Passed policy, idempotency, and confidence checks.",
    }
