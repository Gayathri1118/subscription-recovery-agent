"""Run every failure_event in the batch through the full LLM Integration
phase graph (detector -> diagnosis -> strategy_agent -> policy -> safety
-> executor -> promise_tracker) and report the decision + strategy +
commitment breakdown.

Run:
    python -m scripts.run_policy_safety_pipeline

NOTE: this now makes real Groq API calls -- strategy_agent runs for every
event with at least one eligible strategy, and promise_tracker runs
whenever the LLM picks negotiate_promise_to_pay. For an 80-event batch
that's up to ~120 live calls. Requires GROQ_API_KEY set in .env and
network access to api.groq.com. On the free tier this should complete
without hitting rate limits, but if you do see 429s, rerun -- the script
is idempotent per event (duplicate events just hit the safety gate's
idempotency block on a second pass).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal
from app.models import FailureEvent, Commitment
from app.graph import run_event


def main():
    db = SessionLocal()
    try:
        events = db.query(FailureEvent).all()
        if not events:
            print("No failure_events found. Run `python -m data.generate_synthetic` first.")
            return

        decision_counts = {}
        violation_counts = {}
        strategy_counts = {}
        commitments_before = db.query(Commitment).count()

        for i, event in enumerate(events, start=1):
            result = run_event(db, event)
            decision = result["final_decision"]
            decision_counts[decision] = decision_counts.get(decision, 0) + 1

            for v in result["policy_result"]["violations"]:
                violation_counts[v] = violation_counts.get(v, 0) + 1

            strategy = result.get("proposed_strategy")
            if strategy:
                strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1

            print(f"[{i}/{len(events)}] {event.failure_type:<20} strategy={strategy} -> {decision}")

        db.commit()
        commitments_after = db.query(Commitment).count()

        total = len(events)
        print()
        print(f"LLM Integration phase pipeline run: {total} events")
        print(f"Decision breakdown: {decision_counts}")
        print(f"Policy violations breakdown: {violation_counts}")
        print(f"Strategy breakdown (LLM-chosen): {strategy_counts}")
        print(f"Commitments created this run: {commitments_after - commitments_before} "
              f"(pending customer follow-through -- see docs/what-broke.md and app/graph.py's "
              f"promise_tracker_node for why these don't get a recovery_outcomes row yet)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
