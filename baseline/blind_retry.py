"""Baseline: "always retry once, no diagnosis, no Hinglish negotiation."

Run:
    python -m baseline.blind_retry

This is deliberately dumb — one mock_execute call per failure event, no
failure-type-aware strategy, no promise tracking, no escalation. Its only
job is to produce a recovery-rate number to put next to the real agent's
number (spec section 10). That comparison is the single most persuasive
thing in the demo, so this has to run cleanly before anything smarter
gets built on top of it.

Writes one row per event to recovery_outcomes (strategy="baseline_blind_retry")
and one audit row per event to agent_actions (node="baseline").
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal
from app.models import FailureEvent, AgentAction, RecoveryOutcome
from mock_provider.provider import mock_execute

STRATEGY_LABEL = "baseline_blind_retry"


def run_baseline():
    db = SessionLocal()
    try:
        events = db.query(FailureEvent).all()
        if not events:
            print("No failure_events found. Run `python -m data.generate_synthetic` first.")
            return

        # Skip events this baseline has already processed (idempotent re-runs).
        already_done = {
            row.failure_event_id
            for row in db.query(RecoveryOutcome.failure_event_id)
            .filter(RecoveryOutcome.strategy == STRATEGY_LABEL)
            .all()
        }

        recovered_count = 0
        recovered_amount_total = 0.0
        outcome_counts = {}

        for event in events:
            if event.id in already_done:
                continue

            outcome = mock_execute(
                event_id=str(event.id),
                attempt_number=event.attempt_number,
                already_recovered=(event.status == "recovered"),
                is_duplicate=False,
            )
            outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1

            recovery_status = "recovered" if outcome == "SUCCESS" else "failed"
            recovered_amount = float(event.amount) if outcome == "SUCCESS" else None

            db.add(AgentAction(
                failure_event_id=event.id,
                node="baseline",
                output={"outcome": outcome},
                decision="ALLOWED",
                reasoning="Blind retry: no diagnosis, no policy check, single attempt.",
            ))
            db.add(RecoveryOutcome(
                failure_event_id=event.id,
                strategy=STRATEGY_LABEL,
                recovered_amount=recovered_amount,
                recovery_status=recovery_status,
                attempt_count=1,
                completed_at=datetime.now(timezone.utc),
            ))

            if outcome == "SUCCESS":
                recovered_count += 1
                recovered_amount_total += float(event.amount)

        db.commit()

        total = len(events)
        rate = recovered_count / total if total else 0.0
        print(f"Baseline (blind retry): {total} cases -> "
              f"₹{recovered_amount_total:,.2f} recovered, {rate:.1%} rate")
        print(f"Outcome breakdown: {outcome_counts}")
    finally:
        db.close()


if __name__ == "__main__":
    run_baseline()
