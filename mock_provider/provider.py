"""Mock payment/messaging provider.

Clearly simulated — no live Razorpay calls.

Outcome is deterministic given (seed, event_id, attempt_number[, strategy]):
hash the inputs into [0, 1) and bucket the result. Same seed -> same
outcome every run, so a rehearsed demo reproduces exactly.

ALREADY_PAID and DUPLICATE are not random — they reflect real state passed
in by the caller (the safety gate's idempotency check owns that logic).
This module only decides the "did the attempt itself succeed" question.

STRATEGY-AWARE OUTCOMES (added during Evaluation phase, see
docs/what-broke.md Entry 5): the baseline's call site (baseline/blind_retry.py)
does NOT pass `strategy`, so it always uses OUTCOME_THRESHOLDS with the
original (seed, event_id, attempt_number) hash -- baseline's numbers are
byte-identical to before this change, on purpose, since they were already
verified and documented.

The agent's executor (app/graph.py) DOES pass `strategy`. Two strategies
(retry_same_card, immediate_retry) are mechanically the SAME action as a
blind retry -- same card, same immediate attempt -- so they deliberately
use the same OUTCOME_THRESHOLDS and the same roll as baseline: no
artificial advantage where none is earned. The other three non-negotiation
strategies (request_alt_payment_method, delayed_retry, send_update_card_link)
represent a genuinely DIFFERENT action with a real-world reason to succeed
more often, so they get their own threshold profile and an independent
roll (the strategy name is part of the hash key).
"""
import hashlib
import os

from dotenv import load_dotenv

load_dotenv()

SEED = int(os.getenv("RANDOM_SEED", 42))

# Cumulative probability thresholds for a "fresh" attempt (not already-paid,
# not a duplicate). Ordered SUCCESS -> TEMPORARY_FAILURE -> TIMEOUT.
# This is the "blind retry" profile: used by baseline always, and by any
# agent strategy that's mechanically equivalent to a blind retry.
OUTCOME_THRESHOLDS = [
    ("SUCCESS", 0.55),
    ("TEMPORARY_FAILURE", 0.85),
    ("TIMEOUT", 1.00),
]

# Strategies with their own profile, because they represent a genuinely
# different action than "retry the same thing again":
#   request_alt_payment_method — customer supplies a different payment
#     method entirely, sidestepping whatever was wrong with the original
#     card, so a materially higher success rate is realistic.
#   delayed_retry — waiting a few days lets a genuinely transient
#     insufficient-funds situation (e.g. before payday) resolve itself.
#   send_update_card_link — customer enters a new, non-expired card,
#     which directly fixes the actual problem (unlike blindly retrying
#     the same expired card, which cannot succeed in the real world).
# retry_same_card and immediate_retry are intentionally absent: they fall
# through to OUTCOME_THRESHOLDS, same as baseline, because they're the
# same action baseline already takes.
STRATEGY_OUTCOME_THRESHOLDS = {
    "request_alt_payment_method": [
        ("SUCCESS", 0.75), ("TEMPORARY_FAILURE", 0.90), ("TIMEOUT", 1.00),
    ],
    "delayed_retry": [
        ("SUCCESS", 0.65), ("TEMPORARY_FAILURE", 0.90), ("TIMEOUT", 1.00),
    ],
    "send_update_card_link": [
        ("SUCCESS", 0.70), ("TEMPORARY_FAILURE", 0.90), ("TIMEOUT", 1.00),
    ],
}


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
    strategy: str = None,
) -> str:
    """Return one of SUCCESS | TEMPORARY_FAILURE | TIMEOUT | ALREADY_PAID | DUPLICATE.

    already_recovered and is_duplicate are state checks the caller (safety
    gate) is responsible for computing — this function does not look at
    the database itself, it just resolves the outcome deterministically.

    strategy: optional. Omit (or None) for the original "blind retry"
    behavior -- this is what baseline/blind_retry.py does, and its hash/
    thresholds are UNCHANGED from before strategy-awareness was added, so
    previously-documented baseline numbers remain reproducible exactly.
    Pass a strategy name to get that strategy's own outcome profile where
    one exists (see STRATEGY_OUTCOME_THRESHOLDS); strategies without a
    profile fall back to the same blind-retry thresholds and roll baseline
    uses, because they're mechanically the same action.
    """
    if already_recovered:
        return "ALREADY_PAID"
    if is_duplicate:
        return "DUPLICATE"

    if strategy and strategy in STRATEGY_OUTCOME_THRESHOLDS:
        roll = _deterministic_unit_interval(seed, event_id, attempt_number, strategy)
        thresholds = STRATEGY_OUTCOME_THRESHOLDS[strategy]
    else:
        roll = _deterministic_unit_interval(seed, event_id, attempt_number)
        thresholds = OUTCOME_THRESHOLDS

    for outcome, threshold in thresholds:
        if roll < threshold:
            return outcome
    return "TIMEOUT"  # unreachable given thresholds sum to 1.0, kept as a safe default
