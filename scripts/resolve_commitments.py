"""Resolve pending commitments (Evaluation phase): simulate whether each
customer who made a clear promise-to-pay actually followed through, and
write the final recovery_outcomes row now that the true outcome is known.

Run:
    python -m scripts.resolve_commitments

Deterministic given RANDOM_SEED, same principle as mock_provider/provider.py
and app/conversation_sim.py: same seed -> same kept/broken outcome every
run, so results reproduce exactly.

STATED ASSUMPTION: PROMISE_KEPT_RATE (0.70) models a realistic promise-to-
pay conversion rate for subscription billing collections. This is NOT
derived from this project's own synthetic data or from any measured model
output -- it's an input to the simulation, based on the general pattern in
collections/BNPL literature that an explicit customer commitment converts
meaningfully better than a blind retry attempt (commonly cited in the
65-75% range, varying by channel and follow-up rigor). Treat the resulting
"agent recovery rate" as a demonstration of the ARCHITECTURE (commitment
tracking, deferred outcomes, audit trail), not as a real-world accuracy
claim -- there is no live customer behavior behind this number.
"""
import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from app.db import SessionLocal
from app.models import Commitment, FailureEvent, RecoveryOutcome

load_dotenv()

SEED = int(os.getenv("RANDOM_SEED", 42))
PROMISE_KEPT_RATE = 0.70


def _kept_roll(commitment_id: str, seed: int = SEED) -> float:
    """Hash (seed, commitment_id) into a stable float in [0, 1), same
    pattern as mock_provider/provider.py's payment-outcome hash and
    app/conversation_sim.py's reply picker. Distinct hash suffix
    ("promise_resolution") keeps this draw uncorrelated with the others.
    """
    key = f"{seed}:{commitment_id}:promise_resolution".encode("utf-8")
    digest = hashlib.sha256(key).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def main():
    db = SessionLocal()
    try:
        pending = db.query(Commitment).filter(Commitment.status == "pending").all()
        if not pending:
            print("No pending commitments to resolve. Run the pipeline first "
                  "(python -m scripts.run_policy_safety_pipeline) to create some.")
            return

        kept_count = 0
        broken_count = 0
        skipped_count = 0

        for commitment in pending:
            event = (
                db.query(FailureEvent)
                .filter(FailureEvent.id == commitment.failure_event_id)
                .first()
            )
            if event is None:
                print(f"WARNING: commitment {commitment.id} has no matching "
                      f"failure_event, skipping.")
                skipped_count += 1
                continue

            existing_outcome = (
                db.query(RecoveryOutcome)
                .filter(
                    RecoveryOutcome.failure_event_id == event.id,
                    RecoveryOutcome.strategy == "negotiate_promise_to_pay",
                )
                .first()
            )
            if existing_outcome:
                print(f"WARNING: recovery_outcomes row already exists for "
                      f"event {event.id}, skipping (already resolved).")
                skipped_count += 1
                continue

            kept = _kept_roll(str(commitment.id)) < PROMISE_KEPT_RATE
            commitment.status = "kept" if kept else "broken"

            db.add(RecoveryOutcome(
                failure_event_id=event.id,
                strategy="negotiate_promise_to_pay",
                recovered_amount=float(event.amount) if kept else None,
                recovery_status="recovered" if kept else "failed",
                attempt_count=1,
                completed_at=datetime.now(timezone.utc),
            ))

            if kept:
                kept_count += 1
            else:
                broken_count += 1

        db.commit()

        total = kept_count + broken_count
        print(f"Resolved {total} pending commitments "
              f"(seed={SEED}, assumed kept rate={PROMISE_KEPT_RATE:.0%})")
        print(f"Kept: {kept_count} | Broken: {broken_count} | Skipped: {skipped_count}")
        if total:
            print(f"Actual kept rate this batch: {kept_count / total:.1%}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
