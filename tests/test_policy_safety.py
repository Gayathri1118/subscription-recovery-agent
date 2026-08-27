"""Day 2 regression tests — these four checks ARE the Day 2 checkpoint.

Run: pytest tests/test_policy_safety.py -v

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
from app.policy import MAX_AUTOMATED_AMOUNT, MAX_RETRY_ATTEMPTS


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


def test_four_nodes_logged_in_order(db_session):
    """Checkpoint 1: detector -> diagnosis -> policy -> safety, one row each."""
    event = _new_test_event(db_session, amount=299, attempt_number=0, status="open")
    run_event(db_session, event)

    actions = (
        db_session.query(AgentAction)
        .filter(AgentAction.failure_event_id == event.id)
        .order_by(AgentAction.created_at)
        .all()
    )
    assert [a.node for a in actions] == ["detector", "diagnosis", "policy", "safety"]


def test_high_amount_blocks_at_policy(db_session):
    """Checkpoint 2: amount over MAX_AUTOMATED_AMOUNT blocks at policy."""
    event = _new_test_event(
        db_session, amount=MAX_AUTOMATED_AMOUNT + 1000, attempt_number=0, status="open"
    )
    run_event(db_session, event)

    policy_row = (
        db_session.query(AgentAction)
        .filter(AgentAction.failure_event_id == event.id, AgentAction.node == "policy")
        .first()
    )
    assert policy_row.decision == "BLOCKED"
    assert "AMOUNT_OVER_LIMIT" in policy_row.output["violations"]


def test_max_retries_blocks_at_policy(db_session):
    """Checkpoint 3: attempt_number >= MAX_RETRY_ATTEMPTS blocks at policy."""
    event = _new_test_event(
        db_session, amount=299, attempt_number=MAX_RETRY_ATTEMPTS, status="open"
    )
    run_event(db_session, event)

    policy_row = (
        db_session.query(AgentAction)
        .filter(AgentAction.failure_event_id == event.id, AgentAction.node == "policy")
        .first()
    )
    assert policy_row.decision == "BLOCKED"
    assert "MAX_RETRIES_EXCEEDED" in policy_row.output["violations"]


def test_duplicate_run_blocks_at_safety(db_session):
    """Checkpoint 4: running the SAME event through the graph twice hits the
    idempotency block on the second pass — this is the core safety guarantee.
    """
    event = _new_test_event(db_session, amount=299, attempt_number=0, status="open")

    first_result = run_event(db_session, event)
    assert first_result["final_decision"] == "ALLOWED"

    second_result = run_event(db_session, event)
    assert second_result["final_decision"] == "BLOCKED"
    assert second_result["safety_result"]["reason"] == "duplicate_idempotency_key"


def test_already_recovered_blocks_at_policy(db_session):
    """Bonus: status='recovered' blocks — prevents charging an already-paid customer."""
    event = _new_test_event(db_session, amount=299, attempt_number=0, status="recovered")
    run_event(db_session, event)

    policy_row = (
        db_session.query(AgentAction)
        .filter(AgentAction.failure_event_id == event.id, AgentAction.node == "policy")
        .first()
    )
    assert policy_row.decision == "BLOCKED"
    assert "ALREADY_RECOVERED" in policy_row.output["violations"]
