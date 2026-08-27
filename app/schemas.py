"""Pydantic schemas for the two LLM-backed nodes' structured outputs.

Both schemas are passed to langchain-groq's `.with_structured_output()` so
the model is constrained to return exactly these fields - no free text, no
parsing regexes on our end.

StrategyDecision -> Strategy Agent node (between diagnosis and policy)
PromiseExtraction -> Promise-to-Pay node (after executor)

Language detection is NOT a separate schema/call. It's the
`detected_language` field on PromiseExtraction, per the README: folding it
into the same structured call that extracts the commitment date costs zero
extra API calls / latency, and avoids the unrealistic shortcut of tagging a
customer's language at generation time.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field

# Every strategy that appears anywhere in app/diagnosis.py's STRATEGY_MENU.
# Kept as a Literal (not a free string) so the LLM can only pick from the
# same fixed menu diagnosis.py already constrains it to -- the model ranks
# among valid options, it doesn't invent one. See app/diagnosis.py's
# module docstring for the "AI judgment" boundary this schema encodes.
StrategyName = Literal[
    "retry_same_card",
    "request_alt_payment_method",
    "send_update_card_link",
    "delayed_retry",
    "negotiate_promise_to_pay",
    "immediate_retry",
]

# Matches data/customer_replies.py's four intent buckets exactly.
PromiseIntent = Literal["clear_promise", "vague_stall", "dispute", "silence"]

# Matches data/customer_replies.py's LANGUAGES dict keys exactly.
DetectedLanguage = Literal[
    "hinglish", "tanglish", "tenglish", "kanglish", "malayalam_english",
    "english", "unknown",
]


class StrategyDecision(BaseModel):
    """Strategy Agent node output. The model picks ONE strategy from the
    eligible list diagnosis.py already computed for this failure_type --
    it never sees or picks from the full StrategyName menu unfiltered."""

    strategy: StrategyName = Field(
        description="The single best strategy from the eligible_strategies list provided in the prompt."
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Model's confidence in this strategy choice, 0.0-1.0. "
                     "Below 0.8 triggers ESCALATED at the safety gate (app/safety.py).",
    )
    reasoning: str = Field(
        description="One or two sentences on why this strategy fits this failure_event, for the audit trail."
    )


class PromiseExtraction(BaseModel):
    """Promise-to-Pay node output. One LLM call does double duty: it
    extracts the customer's commitment intent AND identifies what language
    the reply was written in, from the same message."""

    intent: PromiseIntent = Field(
        description="Which of the four intent buckets this reply falls into: "
                     "clear_promise (specific or clearly-resolvable date given), "
                     "vague_stall (non-committal, no date), "
                     "dispute (customer contests the charge), "
                     "silence (empty/non-substantive reply, e.g. 'Ok', an emoji, or blank)."
    )
    promised_date: Optional[str] = Field(
        default=None,
        description="ISO 8601 date (YYYY-MM-DD) the customer committed to, resolved against "
                     "the reference date passed in the prompt (e.g. 'naalaikku'/'kal' -> "
                     "tomorrow's date). Null unless intent == 'clear_promise'.",
    )
    detected_language: DetectedLanguage = Field(
        description="The code-mixed language/script the reply is written in. "
                     "Must be inferred from the message itself, never assumed."
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Model's confidence in this extraction, 0.0-1.0.",
    )
