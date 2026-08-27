"""Deterministic customer-reply simulator for the negotiate_promise_to_pay
strategy. There's no live customer in a synthetic batch run, so the
executor node needs a stand-in reply to hand to the Promise-to-Pay LLM
node -- this picks one from data/customer_replies.py's 120-reply bank.

Deterministic given (seed, event_id), same principle as
mock_provider/provider.py's payment-outcome hash: same seed -> same reply
picked every run, so a rehearsed demo reproduces exactly. Uses a distinct
hash input ("customer_reply" suffix) from the payment-outcome hash so the
two draws aren't correlated with each other.
"""
import hashlib
import os

from dotenv import load_dotenv

from data.customer_replies import ALL_REPLIES

load_dotenv()

SEED = int(os.getenv("RANDOM_SEED", 42))


def pick_customer_reply(event_id: str, seed: int = SEED) -> tuple[str, str, str]:
    """Return (language_code, intent_bucket, reply_text) deterministically
    for this event_id. Draws uniformly across all 120 replies -- every
    language/bucket combination is equally likely to be selected, since
    the bank itself is already balanced (6 replies x 4 buckets x 5 languages).
    """
    key = f"{seed}:{event_id}:customer_reply".encode("utf-8")
    digest = hashlib.sha256(key).hexdigest()
    index = int(digest[:8], 16) % len(ALL_REPLIES)
    return ALL_REPLIES[index]
