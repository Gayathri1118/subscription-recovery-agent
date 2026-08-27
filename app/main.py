"""FastAPI scaffold.

Day 1 scope: health check + read-only views into the data so you can
sanity-check the generator and baseline run without touching Postgres directly.
The LangGraph state machine (detector -> ... -> executor) gets wired in
starting Day 2; this file grows node-by-node from here.
"""
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db import get_db
from app.models import FailureEvent, AgentAction, RecoveryOutcome
from mock_provider.router import router as mock_provider_router

app = FastAPI(title="Subscription Revenue Recovery Agent", version="0.1.0")
app.include_router(mock_provider_router)


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
