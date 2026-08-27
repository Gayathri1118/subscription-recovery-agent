"""POST /mock/recovery/{event_id}/execute — the mock provider endpoint from spec section 8.

Day 1: only checks `already_recovered` (event.status == "recovered").
Duplicate detection via idempotency_key is the Safety Gate's job — wired in
Day 2 — so `is_duplicate` is always False here for now. This endpoint is a
thin HTTP wrapper around mock_provider.provider.mock_execute; the baseline
script calls mock_execute directly rather than going over HTTP.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import FailureEvent
from mock_provider.provider import mock_execute

router = APIRouter(prefix="/mock/recovery", tags=["mock-provider"])


@router.post("/{event_id}/execute")
def execute(event_id: str, db: Session = Depends(get_db)):
    event = db.query(FailureEvent).filter(FailureEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="failure_event not found")

    outcome = mock_execute(
        event_id=str(event.id),
        attempt_number=event.attempt_number,
        already_recovered=(event.status == "recovered"),
        is_duplicate=False,  # TODO Day 2: wire real idempotency check from Safety Gate
    )
    return {"event_id": str(event.id), "attempt_number": event.attempt_number, "outcome": outcome}
