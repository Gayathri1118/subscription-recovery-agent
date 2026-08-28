"""Narrated, single-event walkthrough of the recovery agent -- Evaluation
phase's answer to "show, don't just tell". Picks one real event from the
already-run batch that went the full negotiate_promise_to_pay ->
clear_promise -> commitment -> resolution path, and replays its actual
audit trail (from agent_actions, commitments, recovery_outcomes) with
paced narration.

This is intentionally a REPLAY, not a fresh run: it makes zero LLM calls,
needs no GROQ_API_KEY, and always shows what really happened on your last
full pipeline run -- not a scripted/staged interaction. Meant to stand in
for a terminal recording (asciinema/vhs): run this, record your terminal,
done.

Prerequisite: the full sequence must already have been run at least once --
    python -m data.generate_synthetic
    python -m baseline.blind_retry
    python -m scripts.run_policy_safety_pipeline
    python -m scripts.resolve_commitments

Run:
    python -m scripts.demo
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal
from app.models import FailureEvent, AgentAction, Commitment, RecoveryOutcome

PACE = 0.7  # seconds between narrated beats; set to 0 for an instant run

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"


def beat(text: str = "", pace: float = PACE) -> None:
    print(text)
    time.sleep(pace)


def node_color(decision: str) -> str:
    if decision == "ALLOWED":
        return GREEN
    if decision in ("BLOCKED", "ESCALATED"):
        return RED
    return YELLOW


def pick_demo_event(db):
    """Prefer a KEPT commitment (the happiest path) so the demo shows the
    full architecture paying off; fall back to a BROKEN one if no kept
    commitment exists in this batch, since that's still a real, honestly-
    completed run of the same path -- see README's Evaluation results
    section for why a broken promise here isn't something to hide.
    """
    kept = (
        db.query(Commitment)
        .filter(Commitment.status == "kept")
        .order_by(Commitment.created_at)
        .first()
    )
    if kept:
        return kept
    return (
        db.query(Commitment)
        .filter(Commitment.status == "broken")
        .order_by(Commitment.created_at)
        .first()
    )


def main():
    db = SessionLocal()
    try:
        commitment = pick_demo_event(db)
        if commitment is None:
            print(
                "No resolved commitments found. Run the full sequence first:\n"
                "  python -m data.generate_synthetic\n"
                "  python -m baseline.blind_retry\n"
                "  python -m scripts.run_policy_safety_pipeline\n"
                "  python -m scripts.resolve_commitments"
            )
            return

        event = db.query(FailureEvent).filter(FailureEvent.id == commitment.failure_event_id).first()
        actions = (
            db.query(AgentAction)
            .filter(AgentAction.failure_event_id == event.id)
            .order_by(AgentAction.created_at)
            .all()
        )
        outcomes = {
            o.strategy: o
            for o in db.query(RecoveryOutcome).filter(RecoveryOutcome.failure_event_id == event.id).all()
        }

        print()
        beat(f"{BOLD}{CYAN}=== Subscription Revenue Recovery Agent — live walkthrough ==={RESET}")
        beat(f"{DIM}Replaying a real event from the last pipeline run. No LLM calls made here —{RESET}")
        beat(f"{DIM}this is the actual audit trail, from agent_actions, commitments, and{RESET}")
        beat(f"{DIM}recovery_outcomes. Nothing below is staged.{RESET}\n")

        beat(f"{BOLD}Event {str(event.id)[:8]}{RESET}")
        beat(f"  customer:      {event.customer_id}")
        beat(f"  failure type:  {event.failure_type}")
        beat(f"  amount:        \u20b9{event.amount}")
        beat(f"  attempt #:     {event.attempt_number}\n")

        for i, a in enumerate(actions, start=1):
            color = node_color(a.decision)
            conf = f"  confidence={float(a.confidence):.2f}" if a.confidence is not None else ""
            beat(f"{BOLD}[{i}/{len(actions)}] {a.node.upper()}{RESET}  {color}{a.decision}{RESET}{conf}")
            if a.reasoning:
                beat(f"    {DIM}{a.reasoning}{RESET}")
            if a.output:
                for k, v in a.output.items():
                    beat(f"    {k}: {v}")
            print()

        beat(f"{BOLD}--- Commitment ---{RESET}")
        beat(f"  promised date: {commitment.promised_date}")
        beat(f"  extracted from: \"{commitment.extracted_from_message}\"")
        status_color = GREEN if commitment.status == "kept" else RED
        beat(f"  resolution:    {status_color}{commitment.status.upper()}{RESET}")
        beat(
            f"  {DIM}(seeded 70% assumption, per scripts/resolve_commitments.py — "
            f"a stated simulation input, not a measured result){RESET}\n"
        )

        negotiate_outcome = outcomes.get("negotiate_promise_to_pay")
        baseline_outcome = outcomes.get("baseline_blind_retry")

        beat(f"{BOLD}--- Outcome ---{RESET}")
        if negotiate_outcome:
            recovered = negotiate_outcome.recovery_status == "recovered"
            color = GREEN if recovered else RED
            amt = f"\u20b9{negotiate_outcome.recovered_amount}" if recovered else "\u20b90"
            beat(f"  agent (negotiate_promise_to_pay):  {color}{negotiate_outcome.recovery_status.upper()}{RESET}  {amt}")
        if baseline_outcome:
            recovered = baseline_outcome.recovery_status == "recovered"
            color = GREEN if recovered else RED
            amt = f"\u20b9{baseline_outcome.recovered_amount}" if recovered else "\u20b90"
            beat(f"  baseline (blind retry):            {color}{baseline_outcome.recovery_status.upper()}{RESET}  {amt}")

        print()
        beat(
            f"{DIM}Full 3-part agent-vs-baseline comparison: "
            f"python -m scripts.compare_recovery, or the Comparison tab in frontend/{RESET}"
        )
        beat(f"{DIM}Full run log: docs/what-broke.md{RESET}\n")
    finally:
        db.close()


if __name__ == "__main__":
    main()