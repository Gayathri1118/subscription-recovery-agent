"""Thin wrapper around langchain-groq. Every LLM call in this project goes
through here so there's exactly one place that knows about model names,
retries, and structured-output binding.

Two structured clients are exposed, one per schema in app/schemas.py:
    strategy_llm  -> StrategyDecision  (Strategy Agent node)
    promise_llm   -> PromiseExtraction (Promise-to-Pay node)

Both use Groq's Llama 3.3 70B by default (GROQ_MODEL env var to override).
Ollama fallback (Llama 3.1 8B / Mistral 7B, local, for demo-day outage
insurance) is intentionally NOT wired here yet -- per the priority-cut
list, that's the first thing to drop if time runs short. Wire it later by
adding a second branch here behind an env flag; nothing else in the
codebase should need to change since callers only ever import
strategy_llm / promise_llm / get_llm(schema).
"""
import os

from dotenv import load_dotenv
from langchain_groq import ChatGroq

from app.schemas import PromiseExtraction, StrategyDecision

load_dotenv()

GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")


def _require_api_key() -> str:
    key = os.getenv("GROQ_API_KEY")
    if not key or not key.strip():
        raise RuntimeError(
            "GROQ_API_KEY is not set. Add it to .env (see .env.example) -- "
            "get one at https://console.groq.com/keys."
        )
    return key.strip()


def get_base_llm(temperature: float = 0.0) -> ChatGroq:
    """Raw ChatGroq client, no structured-output binding. temperature=0.0
    by default: we want deterministic-as-possible extraction/decisions,
    not creative variation, for a system whose whole pitch is auditability."""
    return ChatGroq(
        model=GROQ_MODEL,
        temperature=temperature,
        api_key=_require_api_key(),
    )


def get_llm(schema):
    """Return a ChatGroq client bound to structured output for `schema`
    (a Pydantic model). Use this instead of get_base_llm() whenever you
    need a specific shape back -- i.e. almost always in this project."""
    return get_base_llm().with_structured_output(schema)


# Pre-bound clients for the two nodes that actually call the LLM.
# Constructed lazily on first use (module import shouldn't fail just
# because GROQ_API_KEY isn't set yet -- e.g. during `pytest --collect-only`).
_strategy_llm = None
_promise_llm = None


def strategy_llm():
    global _strategy_llm
    if _strategy_llm is None:
        _strategy_llm = get_llm(StrategyDecision)
    return _strategy_llm


def promise_llm():
    global _promise_llm
    if _promise_llm is None:
        _promise_llm = get_llm(PromiseExtraction)
    return _promise_llm
