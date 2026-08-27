"""Generate a seeded batch of synthetic subscription failure events.

Run:
    python -m data.generate_synthetic

Writes rows to `failure_events` and a holdout manifest to
data/holdout_ids.json (20% of event IDs, untouched by prompt tuning
per spec section 9 — don't read this file until final evaluation).

Deterministic: same RANDOM_SEED always produces the same batch, which is
what lets you rehearse the demo and get the same numbers every time.
"""
import json
import os
import random
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from faker import Faker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal, engine, Base
from app.models import FailureEvent, FAILURE_TYPES

load_dotenv()

SEED = int(os.getenv("RANDOM_SEED", 42))
NUM_EVENTS = int(os.getenv("NUM_FAILURE_EVENTS", 80))
HOLDOUT_FRACTION = 0.20

# Realistic-ish weighting: card declines and insufficient funds are the
# most common failure reasons in subscription billing; gateway timeouts
# are rarer and usually self-resolve on retry.
FAILURE_TYPE_WEIGHTS = {
    "card_declined": 0.35,
    "insufficient_funds": 0.30,
    "expired_card": 0.20,
    "gateway_timeout": 0.15,
}

# Indian subscription price points (INR) — mix of low, mid, high tier plans.
AMOUNT_CHOICES = [199, 299, 499, 999, 1499, 2999, 4999, 7999]


def weighted_failure_type(rng: random.Random) -> str:
    types, weights = zip(*FAILURE_TYPE_WEIGHTS.items())
    return rng.choices(types, weights=weights, k=1)[0]


def generate_events(n: int, seed: int):
    fake = Faker()
    Faker.seed(seed)
    rng = random.Random(seed)

    events = []
    for _ in range(n):
        failure_type = weighted_failure_type(rng)
        # attempt_number: mostly first-time failures, a tail of repeat
        # failures so the policy engine's MAX_RETRY_ATTEMPTS rule (section 6)
        # and demo case F (section 12) actually get exercised.
        attempt_number = rng.choices([0, 1, 2, 3], weights=[0.55, 0.25, 0.12, 0.08], k=1)[0]

        event_id = uuid.UUID(int=rng.getrandbits(128), version=4)

        events.append(
            FailureEvent(
                id=event_id,
                customer_id=f"cust_{fake.unique.random_number(digits=8, fix_len=True)}",
                subscription_id=f"sub_{fake.unique.random_number(digits=8, fix_len=True)}",
                failure_type=failure_type,
                amount=rng.choice(AMOUNT_CHOICES),
                attempt_number=attempt_number,
                status="open",
            )
        )

def main():
    print(f"Generating {NUM_EVENTS} synthetic failure events (seed={SEED})...")

    Base.metadata.create_all(bind=engine)  # no-op if schema.sql already ran

    events = generate_events(NUM_EVENTS, SEED)

    db = SessionLocal()
    try:
        existing = db.query(FailureEvent).count()
        if existing:
            print(f"WARNING: {existing} failure_events already in the DB. "
                  f"Skipping insert to avoid duplicating the batch. "
                  f"Truncate the table first if you want to regenerate.")
            return

        db.add_all(events)
        db.commit()
        for e in events:
            db.refresh(e)

        # Holdout manifest: 20% of IDs set aside, per spec section 9.
        rng = random.Random(SEED)
        ids = [str(e.id) for e in events]
        holdout_size = round(len(ids) * HOLDOUT_FRACTION)
        holdout_ids = rng.sample(ids, holdout_size)

        holdout_path = Path(__file__).resolve().parent / "holdout_ids.json"
        with open(holdout_path, "w") as f:
            json.dump({"seed": SEED, "holdout_ids": holdout_ids}, f, indent=2)

        print(f"Inserted {len(events)} failure_events.")
        print(f"Holdout set ({holdout_size} ids, {HOLDOUT_FRACTION:.0%}) written to {holdout_path}")
        print("Do not tune prompts against holdout IDs until final evaluation (spec section 9).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
