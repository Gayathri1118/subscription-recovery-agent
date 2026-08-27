"""Deprecated — superseded by data/customer_replies.py, which now covers
Hindi, Tamil, Telugu, Kannada, and Malayalam code-mixed replies (not just
Hinglish). Kept as a thin re-export so any old `from data.hinglish_replies
import BUCKETS` doesn't break.
"""
from data.customer_replies import HINGLISH as BUCKETS  # noqa: F401

CLEAR_PROMISE = BUCKETS["clear_promise"]
VAGUE_STALL = BUCKETS["vague_stall"]
DISPUTE = BUCKETS["dispute"]
SILENCE = BUCKETS["silence"]
