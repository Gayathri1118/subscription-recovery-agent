"""Compare the agent's recovery performance against the baseline
(blind-retry) strategy, on the SAME set of events -- the single most
important number for this project (Evaluation phase).

Run:
    python -m scripts.compare_recovery

Prerequisite: both baseline/blind_retry.py and
scripts/run_policy_safety_pipeline.py must have been run against the
current batch, and scripts/resolve_commitments.py should be run too if
you want pending negotiate_promise_to_pay commitments counted as
recovered/failed rather than still-pending.

FAIRNESS NOTE: both rates use the SAME denominator -- the total number of
failure_events in the batch -- not just the events each approach happened
to act on. This matters because the agent's safety gate deliberately
declines to act on some events (amount over the automation limit, too
many retry attempts already) and routes them to human review instead.
Those are correctly counted as "not recovered" in the headline rate, since
that's real money not recovered automatically -- but the breakdown below
separates "declined for a real policy reason" from "attempted and failed"
so the number isn't misleading in either direction.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal
from app.models import FailureEvent, RecoveryOutcome, AgentAction, Commitment

BASELINE_STRATEGY = "baseline_blind_retry"


def main():
    db = SessionLocal()
    try:
        total_events = db.query(FailureEvent).count()
        if total_events == 0:
            print("No failure_events found. Run `python -m data.generate_synthetic` first.")
            return

        # --- Baseline ---
        baseline_outcomes = (
            db.query(RecoveryOutcome)
            .filter(RecoveryOutcome.strategy == BASELINE_STRATEGY)
            .all()
        )
        if not baseline_outcomes:
            print("No baseline outcomes found. Run `python -m baseline.blind_retry` first.")
            return

        baseline_recovered = [o for o in baseline_outcomes if o.recovery_status == "recovered"]
        baseline_amount = sum(float(o.recovered_amount or 0) for o in baseline_recovered)
        baseline_rate = len(baseline_recovered) / total_events

        # --- Agent: one outcome row per event, across every non-baseline strategy ---
        agent_outcomes = {
            o.failure_event_id: o
            for o in db.query(RecoveryOutcome)
            .filter(RecoveryOutcome.strategy != BASELINE_STRATEGY)
            .all()
        }

        # Events the safety gate declined to act on (BLOCKED or ESCALATED),
        # so they never reached the executor and have no recovery_outcomes row.
        safety_decisions = {
            a.failure_event_id: a.decision
            for a in db.query(AgentAction).filter(AgentAction.node == "safety").all()
        }

        # Commitments still awaiting resolution (negotiate_promise_to_pay,
        # clear_promise, but scripts/resolve_commitments.py hasn't run yet
        # or hasn't reached this one).
        pending_commitment_event_ids = {
            c.failure_event_id
            for c in db.query(Commitment).filter(Commitment.status == "pending").all()
        }

        agent_recovered_amount = 0.0
        agent_recovered_count = 0
        declined_by_safety = 0
        attempted_but_failed = 0
        still_pending = 0
        unaccounted = 0

        for event in db.query(FailureEvent).all():
            outcome = agent_outcomes.get(event.id)
            if outcome is not None:
                if outcome.recovery_status == "recovered":
                    agent_recovered_count += 1
                    agent_recovered_amount += float(outcome.recovered_amount or 0)
                else:
                    attempted_but_failed += 1
            elif event.id in pending_commitment_event_ids:
                still_pending += 1
            elif safety_decisions.get(event.id) in ("BLOCKED", "ESCALATED"):
                declined_by_safety += 1
            else:
                unaccounted += 1

        agent_rate = agent_recovered_count / total_events

        print(f"Comparison over {total_events} events (same denominator for both):\n")
        print(f"{'':<28}{'Baseline':>15}{'Agent':>15}")
        print(f"{'Recovered (count)':<28}{len(baseline_recovered):>15}{agent_recovered_count:>15}")
        print(f"{'Recovery rate':<28}{baseline_rate:>15.1%}{agent_rate:>15.1%}")
        print(f"{'Amount recovered (Rs)':<28}{baseline_amount:>15,.2f}{agent_recovered_amount:>15,.2f}")

        delta_pp = (agent_rate - baseline_rate) * 100
        delta_amount = agent_recovered_amount - baseline_amount
        print(f"\nDelta: {delta_pp:+.1f} percentage points, "
              f"Rs{delta_amount:+,.2f} vs. baseline")

        print(f"\nAgent breakdown of the {total_events - agent_recovered_count} not counted as recovered:")
        print(f"  Attempted but failed (genuine miss):        {attempted_but_failed}")
        print(f"  Declined by safety gate (policy/confidence): {declined_by_safety}")
        if still_pending:
            print(f"  Still-pending commitments (unresolved):     {still_pending} "
                  f"-- run `python -m scripts.resolve_commitments`")
        if unaccounted:
            print(f"  WARNING -- unaccounted for:                 {unaccounted} "
                  f"(pipeline may not have run for these events)")

        # --- Isolate strategy-selection uplift from the safety trade-off ---
        # The headline numbers above answer "how much does the FULL system
        # (strategy choice + safety gate) recover, on the same denominator
        # as baseline". That conflates two different effects: the safety
        # gate deliberately declining some events (a real, intentional
        # trade-off, not a strategy failure), and the LLM's strategy choice
        # itself. This section isolates the second effect: on ONLY the
        # events the agent actually attempted (i.e. excluding safety
        # declines), how does the agent's recovery rate compare to what
        # baseline achieves on that SAME subset of events?
        attempted_event_ids = set(agent_outcomes.keys())
        baseline_by_event = {o.failure_event_id: o for o in baseline_outcomes}
        baseline_recovered_on_attempted = sum(
            1 for eid in attempted_event_ids
            if eid in baseline_by_event and baseline_by_event[eid].recovery_status == "recovered"
        )
        if attempted_event_ids:
            attempted_agent_rate = agent_recovered_count / len(attempted_event_ids)
            attempted_baseline_rate = baseline_recovered_on_attempted / len(attempted_event_ids)
            print(f"\nStrategy-selection uplift only (same {len(attempted_event_ids)} events "
                  f"the agent actually attempted, safety declines excluded from both sides):")
            print(f"  Baseline rate on this subset: {attempted_baseline_rate:.1%}")
            print(f"  Agent rate on this subset:    {attempted_agent_rate:.1%}")
            print(f"  Delta: {(attempted_agent_rate - attempted_baseline_rate) * 100:+.1f} "
                  f"percentage points -- this isolates whether the LLM's strategy choice "
                  f"itself helps, separate from the safety gate's declines.")

        # --- Negotiation path: revenue baseline structurally cannot reach ---
        negotiate_recovered = [
            o for o in agent_outcomes.values()
            if o.strategy == "negotiate_promise_to_pay" and o.recovery_status == "recovered"
        ]
        if negotiate_recovered:
            negotiate_amount = sum(float(o.recovered_amount or 0) for o in negotiate_recovered)
            print(f"\nNegotiation-path recovery (baseline never negotiates, so this is "
                  f"revenue baseline cannot reach by construction):")
            print(f"  {len(negotiate_recovered)} kept commitments, Rs{negotiate_amount:,.2f} recovered")
    finally:
        db.close()


if __name__ == "__main__":
    main()
