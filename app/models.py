"""ORM models — mirror app/schema.sql exactly. If you change one, change both."""
import uuid

from sqlalchemy import (
    Column, String, Numeric, Integer, DateTime, ForeignKey, Text, Date
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from app.db import Base

FAILURE_TYPES = ("card_declined", "expired_card", "insufficient_funds", "gateway_timeout")
EVENT_STATUSES = ("open", "recovering", "recovered", "escalated", "blocked")
NODES = (
    "detector", "diagnosis", "strategy_agent", "policy",
    "safety", "executor", "promise_tracker", "baseline",
)
DECISIONS = ("ALLOWED", "BLOCKED", "ESCALATED")
COMMITMENT_STATUSES = ("pending", "kept", "broken")
RECOVERY_STATUSES = ("recovered", "failed", "escalated", "blocked")


class FailureEvent(Base):
    __tablename__ = "failure_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(Text, nullable=False)
    subscription_id = Column(Text, nullable=False)
    failure_type = Column(Text, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    attempt_number = Column(Integer, nullable=False, default=0)
    status = Column(Text, nullable=False, default="open")
    created_at = Column(DateTime, server_default=func.now())


class AgentAction(Base):
    __tablename__ = "agent_actions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    failure_event_id = Column(UUID(as_uuid=True), ForeignKey("failure_events.id"), nullable=False)
    node = Column(Text, nullable=False)
    output = Column(JSONB)
    confidence = Column(Numeric(4, 3))
    decision = Column(Text)
    reasoning = Column(Text)
    idempotency_key = Column(Text)
    created_at = Column(DateTime, server_default=func.now())


class Commitment(Base):
    __tablename__ = "commitments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    failure_event_id = Column(UUID(as_uuid=True), ForeignKey("failure_events.id"), nullable=False)
    promised_date = Column(Date)
    status = Column(Text, nullable=False, default="pending")
    extracted_from_message = Column(Text)
    created_at = Column(DateTime, server_default=func.now())


class RecoveryOutcome(Base):
    __tablename__ = "recovery_outcomes"

    failure_event_id = Column(UUID(as_uuid=True), ForeignKey("failure_events.id"), primary_key=True)
    strategy = Column(Text, primary_key=True)
    recovered_amount = Column(Numeric(12, 2))
    recovery_status = Column(Text, nullable=False)
    attempt_count = Column(Integer, nullable=False, default=0)
    completed_at = Column(DateTime)
