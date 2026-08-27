"""Run every failure_event in the batch through the Day 2 graph
(detector -> diagnosis -> policy -> safety) and report the decision
breakdown. No LLM calls — this is the deterministic skeleton only.

Run:
    python -m scripts.run_day2_pipeline
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal
from app.models import FailureEvent
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

        for event in events:
            result = run_event(db, event)
            decision = result["final_decision"]
            decision_counts[decision] = decision_counts.get(decision, 0) + 1

            for v in result["policy_result"]["violations"]:
                violation_counts[v] = violation_counts.get(v, 0) + 1

        db.commit()

        total = len(events)
        print(f"Day 2 pipeline run: {total} events")
        print(f"Decision breakdown: {decision_counts}")
        print(f"Policy violations breakdown: {violation_counts}")
        print()
        print("Note: proposed_strategy is a Day-2 placeholder (first eligible "
              "strategy, confidence=1.0) since the Strategy Agent doesn't exist "
              "until Day 3 — so ESCALATED should be 0 here and ALLOWED should "
              "dominate. Once Day 3 wires in real LLM confidence, expect some "
              "events to escalate on confidence < 0.8.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
