"""Policy & Safety phase regression tests, updated for LLM Integration
phase's expanded graph -- these checks ARE the project's core checkpoints.

Run: pytest tests/test_policy_safety.py -v

IMPORTANT: as of LLM Integration phase, two tests below
(test_pipeline_prefix_logged_in_order and test_duplicate_run_blocks_at_safety)
call the full graph via run_event(), which now makes REAL Groq API calls
(strategy_agent always runs; promise_tracker runs if the LLM picks
negotiate_promise_to_pay). These tests require GROQ_API_KEY to be set and
network access to api.groq.com, and are no longer instant/free the way the
Policy & Safety phase checkpoint was. The three policy-only tests below
deliberately call check_policy() directly instead of run_event(), so they
stay fast/free/deterministic -- they're testing policy.py's logic, which
has nothing to do with the LLM, so there's no reason to pay for and wait
on a Groq call just to reach them via the full pipeline.

Each test either uses a real event from the seeded batch if one happens to
match the needed condition, or constructs a transient one (flushed, not
committed) so the tests don't depend on exact batch contents. The db
session fixture rolls back after every test, so nothing here pollutes your
real audit trail.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.db import SessionLocal
from app.models import FailureEvent, AgentAction
from app.graph import run_event
from app.policy import check_policy, MAX_AUTOMATED_AMOUNT, MAX_RETRY_ATTEMPTS
from app.safety import check_safety
from app.diagnosis import diagnose


@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


def _new_test_event(db, **kwargs):
    """Always construct a fresh, isolated event for these tests (flushed,
    not committed) rather than reusing a real batch event. Batch events
    already carry a `baseline` agent_actions row from baseline/blind_retry.py,
    which would pollute the node-ordering assertions below — this bit us
    on the first real test run (see docs/what-broke.md).
    """
    base = db.query(FailureEvent).first()
    assert base is not None, "No failure_events in DB — run `python -m data.generate_synthetic` first."

    new_event = FailureEvent(
        customer_id="test_customer_policy_safety",
        subscription_id="test_sub_policy_safety",
        failure_type=kwargs.get("failure_type", base.failure_type),
        amount=kwargs.get("amount", base.amount),
        attempt_number=kwargs.get("attempt_number", base.attempt_number),
        status=kwargs.get("status", "open"),
    )
    db.add(new_event)
    db.flush()
    return new_event

@pytest.mark.requires_groq
def test_pipeline_prefix_logged_in_order(db_session):
    """Checkpoint 1: detector -> diagnosis -> strategy_agent -> policy -> safety
    is always the prefix logged for any ALLOWED-through-safety event, in order.
    We only assert the PREFIX (not the full tail) because whether executor and
    promise_tracker run next depends on which strategy the live LLM actually
    picks for this failure_type -- that's a real model call, not scripted.

    Requires GROQ_API_KEY + network (strategy_agent makes a real Groq call).
    """
    event = _new_test_event(db_session, amount=299, attempt_number=0, status="open")
    run_event(db_session, event)

    actions = (
        db_session.query(AgentAction)
        .filter(AgentAction.failure_event_id == event.id)
        .order_by(AgentAction.created_at)
        .all()
    )
    node_sequence = [a.node for a in actions]
    expected_prefix = ["detector", "diagnosis", "strategy_agent", "policy", "safety"]
    assert node_sequence[: len(expected_prefix)] == expected_prefix

    # If it went on to executor, that's fine -- just confirm executor (and
    # promise_tracker, if present) only ever appear AFTER the fixed prefix,
    # never interleaved into it.
    for extra_node in node_sequence[len(expected_prefix):]:
        assert extra_node in ("executor", "promise_tracker")


def test_high_amount_blocks_at_policy():
    """Checkpoint 2: amount over MAX_AUTOMATED_AMOUNT blocks at policy.
    Calls check_policy() directly -- this is pure policy.py logic, unrelated
    to the LLM, so there's no reason to route it through a real Groq call.
    """
    result = check_policy(
        event=type("E", (), {"amount": MAX_AUTOMATED_AMOUNT + 1000, "attempt_number": 0, "status": "open"})(),
        proposed_strategy="retry_same_card",
        eligible_strategies=["retry_same_card", "request_alt_payment_method"],
    )
    assert result["decision"] == "BLOCKED"
    assert "AMOUNT_OVER_LIMIT" in result["violations"]


def test_max_retries_blocks_at_policy():
    """Checkpoint 3: attempt_number >= MAX_RETRY_ATTEMPTS blocks at policy."""
    result = check_policy(
        event=type("E", (), {"amount": 299, "attempt_number": MAX_RETRY_ATTEMPTS, "status": "open"})(),
        proposed_strategy="retry_same_card",
        eligible_strategies=["retry_same_card", "request_alt_payment_method"],
    )
    assert result["decision"] == "BLOCKED"
    assert "MAX_RETRIES_EXCEEDED" in result["violations"]


def test_already_recovered_blocks_at_policy():
    """Bonus: status='recovered' blocks — prevents charging an already-paid customer."""
    result = check_policy(
        event=type("E", (), {"amount": 299, "attempt_number": 0, "status": "recovered"})(),
        proposed_strategy="retry_same_card",
        eligible_strategies=["retry_same_card", "request_alt_payment_method"],
    )
    assert result["decision"] == "BLOCKED"
    assert "ALREADY_RECOVERED" in result["violations"]


def test_strategy_not_in_eligible_list_blocks_at_policy():
    """Bonus: a strategy outside diagnosis's eligible list is always blocked,
    regardless of what the LLM (or a placeholder) proposed -- this is the
    guardrail that keeps the model from ever acting outside its constrained menu.
    """
    result = check_policy(
        event=type("E", (), {"amount": 299, "attempt_number": 0, "status": "open"})(),
        proposed_strategy="not_a_real_strategy",
        eligible_strategies=["retry_same_card", "request_alt_payment_method"],
    )
    assert result["decision"] == "BLOCKED"
    assert "STRATEGY_NOT_ALLOWED" in result["violations"]


def test_duplicate_run_blocks_at_safety(db_session):
    """Checkpoint 4: calling check_safety() twice for the SAME (event,
    attempt_number) hits the idempotency block on the second call — this is
    the core safety guarantee. Calls check_safety() directly with a fixed
    confidence (0.9, above threshold) rather than going through run_event(),
    so this test doesn't depend on what confidence the live LLM happens to
    return on a given run — it's testing app/safety.py's own guarantee, not
    the LLM's behavior.
    """
    event = _new_test_event(db_session, amount=299, attempt_number=0, status="open")
    policy_result = {"decision": "ALLOWED", "violations": []}

    first_result = check_safety(db_session, event, policy_result, confidence=0.9)
    assert first_result["decision"] == "ALLOWED"
    db_session.add(AgentAction(
        failure_event_id=event.id, node="safety", decision="ALLOWED",
        reasoning=first_result["reasoning"], confidence=0.9,
        idempotency_key=first_result["idempotency_key"],
    ))
    db_session.flush()

    second_result = check_safety(db_session, event, policy_result, confidence=0.9)
    assert second_result["decision"] == "BLOCKED"
    assert second_result["reason"] == "duplicate_idempotency_key"