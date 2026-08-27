"""Mock payment/messaging provider.

Clearly simulated — no live Razorpay calls (per spec section 4, don't burn
buildathon time on live test-mode auth).

Outcome is deterministic given (seed, event_id, attempt_number): hash the
inputs into [0, 1) and bucket the result. Same seed -> same outcome every
run, so a rehearsed demo reproduces exactly.

ALREADY_PAID and DUPLICATE are not random — they reflect real state passed
in by the caller (the safety gate's idempotency check owns that logic,
wired in Day 2). This module only decides the "did the retry attempt
itself succeed" question.
"""
import hashlib
import os

from dotenv import load_dotenv

load_dotenv()

SEED = int(os.getenv("RANDOM_SEED", 42))

# Cumulative probability thresholds for a "fresh" attempt (not already-paid,
# not a duplicate). Ordered SUCCESS -> TEMPORARY_FAILURE -> TIMEOUT.
OUTCOME_THRESHOLDS = [
    ("SUCCESS", 0.55),
    ("TEMPORARY_FAILURE", 0.85),
    ("TIMEOUT", 1.00),
]


def _deterministic_unit_interval(*parts: str) -> float:
    """Hash the given parts into a stable float in [0, 1)."""
    key = ":".join(str(p) for p in parts).encode("utf-8")
    digest = hashlib.sha256(key).hexdigest()
    # Use the first 8 hex chars as a big int, normalize to [0, 1).
    return int(digest[:8], 16) / 0xFFFFFFFF


def mock_execute(
    event_id: str,
    attempt_number: int,
    already_recovered: bool = False,
    is_duplicate: bool = False,
    seed: int = SEED,
) -> str:
    """Return one of SUCCESS | TEMPORARY_FAILURE | TIMEOUT | ALREADY_PAID | DUPLICATE.

    already_recovered and is_duplicate are state checks the caller (safety
    gate) is responsible for computing — this function does not look at
    the database itself, it just resolves the outcome deterministically.
    """
    if already_recovered:
        return "ALREADY_PAID"
    if is_duplicate:
        return "DUPLICATE"

    roll = _deterministic_unit_interval(seed, event_id, attempt_number)
    for outcome, threshold in OUTCOME_THRESHOLDS:
        if roll < threshold:
            return outcome
    return "TIMEOUT"  # unreachable given thresholds sum to 1.0, kept as a safe default
