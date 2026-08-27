"""Detector node — rule-based, no LLM.

Your synthetic generator already assigns `failure_type` on every event, so
this node is mostly a validation/normalization pass today. It's still a
real node (not skipped) because:
  1. A future real-Razorpay-webhook version needs somewhere to classify
     raw gateway error codes into these four buckets.
  2. The audit trail should have a `detector` row for every event, even
     when the decision is trivially ALLOWED.
"""
from app.models import FAILURE_TYPES


def detect(event) -> dict:
    """Validate the event's failure_type against the known set.

    Returns a plain dict (not an ORM object) so this stays trivially
    unit-testable without a DB session.
    """
    if event.failure_type not in FAILURE_TYPES:
        return {
            "failure_type": event.failure_type,
            "valid": False,
            "reasoning": f"'{event.failure_type}' is not a recognized failure_type",
        }
    return {
        "failure_type": event.failure_type,
        "valid": True,
        "reasoning": f"failure_type={event.failure_type} recognized",
    }
