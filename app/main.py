"""FastAPI scaffold.

Day 1 scope: health check + read-only views into the data so you can
sanity-check the generator and baseline run without touching Postgres directly.
The LangGraph state machine (detector -> ... -> executor) gets wired in
starting Day 2; this file grows node-by-node from here.
"""
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db import get_db
from app.models import FailureEvent, AgentAction, RecoveryOutcome, Commitment
from mock_provider.router import router as mock_provider_router

app = FastAPI(title="Subscription Revenue Recovery Agent", version="0.1.0")
app.include_router(mock_provider_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite's default dev port
    allow_methods=["*"],
    allow_headers=["*"],
)

BASELINE_STRATEGY = "baseline_blind_retry"


@app.get("/metrics/comparison")
def comparison(db: Session = Depends(get_db)):
    """JSON version of scripts/compare_recovery.py's 3-part output, for the UI.

    IMPORTANT: this route must stay ABOVE /metrics/{strategy} below --
    FastAPI matches routes in declaration order, so if the parameterized
    route came first, a request to /metrics/comparison would be matched as
    strategy="comparison" instead of hitting this handler.
    """
    total_events = db.query(FailureEvent).count()
    if total_events == 0:
        raise HTTPException(status_code=404, detail="No failure_events found.")

    baseline_outcomes = db.query(RecoveryOutcome).filter(
        RecoveryOutcome.strategy == BASELINE_STRATEGY
    ).all()
    if not baseline_outcomes:
        raise HTTPException(status_code=404, detail="No baseline outcomes found.")

    baseline_recovered = [o for o in baseline_outcomes if o.recovery_status == "recovered"]
    baseline_amount = sum(float(o.recovered_amount or 0) for o in baseline_recovered)
    baseline_rate = len(baseline_recovered) / total_events

    agent_outcomes = {
        o.failure_event_id: o
        for o in db.query(RecoveryOutcome).filter(RecoveryOutcome.strategy != BASELINE_STRATEGY).all()
    }
    safety_decisions = {
        a.failure_event_id: a.decision
        for a in db.query(AgentAction).filter(AgentAction.node == "safety").all()
    }
    pending_ids = {
        c.failure_event_id
        for c in db.query(Commitment).filter(Commitment.status == "pending").all()
    }

    agent_recovered_amount = 0.0
    agent_recovered_count = 0
    declined_by_safety = 0
    attempted_but_failed = 0
    still_pending = 0

    for event in db.query(FailureEvent).all():
        outcome = agent_outcomes.get(event.id)
        if outcome is not None:
            if outcome.recovery_status == "recovered":
                agent_recovered_count += 1
                agent_recovered_amount += float(outcome.recovered_amount or 0)
            else:
                attempted_but_failed += 1
        elif event.id in pending_ids:
            still_pending += 1
        elif safety_decisions.get(event.id) in ("BLOCKED", "ESCALATED"):
            declined_by_safety += 1

    agent_rate = agent_recovered_count / total_events

    attempted_ids = set(agent_outcomes.keys())
    baseline_by_event = {o.failure_event_id: o for o in baseline_outcomes}
    baseline_recovered_on_attempted = sum(
        1 for eid in attempted_ids
        if eid in baseline_by_event and baseline_by_event[eid].recovery_status == "recovered"
    )
    attempted_agent_rate = agent_recovered_count / len(attempted_ids) if attempted_ids else None
    attempted_baseline_rate = (
        baseline_recovered_on_attempted / len(attempted_ids) if attempted_ids else None
    )

    negotiate_recovered = [
        o for o in agent_outcomes.values()
        if o.strategy == "negotiate_promise_to_pay" and o.recovery_status == "recovered"
    ]
    negotiate_amount = sum(float(o.recovered_amount or 0) for o in negotiate_recovered)

    return {
        "total_events": total_events,
        "baseline": {
            "recovered_count": len(baseline_recovered),
            "recovery_rate": round(baseline_rate, 4),
            "recovered_amount": round(baseline_amount, 2),
        },
        "agent": {
            "recovered_count": agent_recovered_count,
            "recovery_rate": round(agent_rate, 4),
            "recovered_amount": round(agent_recovered_amount, 2),
            "attempted_but_failed": attempted_but_failed,
            "declined_by_safety": declined_by_safety,
            "still_pending": still_pending,
        },
        "strategy_selection_uplift": {
            "attempted_count": len(attempted_ids),
            "baseline_rate_on_subset": round(attempted_baseline_rate, 4) if attempted_baseline_rate is not None else None,
            "agent_rate_on_subset": round(attempted_agent_rate, 4) if attempted_agent_rate is not None else None,
        },
        "negotiation_only": {
            "kept_commitments": len(negotiate_recovered),
            "recovered_amount": round(negotiate_amount, 2),
        },
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/failure-events")
def list_failure_events(db: Session = Depends(get_db), limit: int = 100):
    events = db.query(FailureEvent).limit(limit).all()
    return [
        {
            "id": str(e.id),
            "customer_id": e.customer_id,
            "subscription_id": e.subscription_id,
            "failure_type": e.failure_type,
            "amount": float(e.amount),
            "attempt_number": e.attempt_number,
            "status": e.status,
        }
        for e in events
    ]


@app.get("/failure-events/{event_id}")
def get_failure_event(event_id: str, db: Session = Depends(get_db)):
    event = db.query(FailureEvent).filter(FailureEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="failure_event not found")

    actions = (
        db.query(AgentAction)
        .filter(AgentAction.failure_event_id == event_id)
        .order_by(AgentAction.created_at)
        .all()
    )
    outcomes = (
        db.query(RecoveryOutcome)
        .filter(RecoveryOutcome.failure_event_id == event_id)
        .all()
    )
    return {
        "id": str(event.id),
        "customer_id": event.customer_id,
        "failure_type": event.failure_type,
        "amount": float(event.amount),
        "status": event.status,
        "actions": [
            {
                "node": a.node,
                "decision": a.decision,
                "confidence": float(a.confidence) if a.confidence is not None else None,
                "reasoning": a.reasoning,
                "output": a.output,
            }
            for a in actions
        ],
        "outcomes": [
            {
                "strategy": o.strategy,
                "recovery_status": o.recovery_status,
                "recovered_amount": float(o.recovered_amount) if o.recovered_amount is not None else None,
                "attempt_count": o.attempt_count,
            }
            for o in outcomes
        ],
    }


@app.get("/metrics/{strategy}")
def metrics_for_strategy(strategy: str, db: Session = Depends(get_db)):
    """Aggregate metrics for one strategy label (e.g. 'baseline_blind_retry').

    Used to produce the section-10 baseline-vs-agent comparison table.
    """
    total = db.query(func.count(RecoveryOutcome.failure_event_id)).filter(
        RecoveryOutcome.strategy == strategy
    ).scalar()
    if not total:
        raise HTTPException(status_code=404, detail=f"no outcomes recorded for strategy '{strategy}'")

    recovered = db.query(func.count(RecoveryOutcome.failure_event_id)).filter(
        RecoveryOutcome.strategy == strategy,
        RecoveryOutcome.recovery_status == "recovered",
    ).scalar()
    recovered_amount = db.query(func.coalesce(func.sum(RecoveryOutcome.recovered_amount), 0)).filter(
        RecoveryOutcome.strategy == strategy,
        RecoveryOutcome.recovery_status == "recovered",
    ).scalar()

    return {
        "strategy": strategy,
        "total_cases": total,
        "recovered_cases": recovered,
        "recovery_rate": round(recovered / total, 4),
        "recovered_amount": float(recovered_amount),
    }