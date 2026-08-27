"""LangGraph state machine -- LLM Integration phase scope:
detector -> diagnosis -> strategy_agent -> policy -> safety -> executor -> promise_tracker

Two real LLM calls now exist in this graph:
  strategy_agent   -> picks ONE strategy from diagnosis's eligible list + confidence
  promise_tracker  -> extracts intent/date/language from a customer's reply
                       (only reached when the chosen strategy is
                       negotiate_promise_to_pay)

Everything else (policy, safety) stays deterministic code, unchanged in
behavior from Policy & Safety phase -- they just now receive a real
confidence value instead of the confidence=1.0 placeholder.

Every node still writes exactly one row to `agent_actions`, so the graph
run for any event is fully reconstructable from the audit trail alone.

Routing after safety: only ALLOWED events reach executor (BLOCKED/ESCALATED
stop here -- that's the safety gate doing its job). Only events where the
LLM chose negotiate_promise_to_pay reach promise_tracker after executor;
every other strategy's outcome is already fully known once executor runs.
"""
from datetime import datetime, timezone
from typing import TypedDict, Optional

from langgraph.graph import StateGraph, END
from sqlalchemy.orm import Session

from app.detector import detect
from app.diagnosis import diagnose
from app.policy import check_policy
from app.safety import check_safety
from app.models import AgentAction, FailureEvent, Commitment, RecoveryOutcome
from app.llm_client import strategy_llm, promise_llm, invoke_with_retry
from app.conversation_sim import pick_customer_reply
from mock_provider.provider import mock_execute

STRATEGY_PROMPT_TEMPLATE = """You are choosing a recovery strategy for a failed subscription payment.

Failure type: {failure_type}
Amount: Rs.{amount}
Attempt number so far: {attempt_number}
Eligible strategies (choose exactly one of these, never anything else): {eligible_strategies}

Guidance on weighing the options, where more than one is eligible:
- For insufficient_funds specifically: a first-time failure (attempt_number
  0) is often transient -- the customer's account may simply be short until
  their next payday, so an automatic delayed_retry a few days out is
  reasonable. But if this is a REPEAT insufficient_funds failure
  (attempt_number 1 or higher), an unattended retry has already failed at
  least once -- at that point, getting the customer's explicit commitment
  via negotiate_promise_to_pay (a specific date they commit to) is more
  likely to actually recover the payment than retrying blind again.
- For card_declined: retry_same_card is reasonable on a first attempt;
  request_alt_payment_method is better once retrying the same card has
  already failed, since the card itself is likely the problem.

Pick the single best strategy for this situation and explain briefly why."""

PROMISE_PROMPT_TEMPLATE = """You are extracting a payment commitment from a customer's reply to a \
payment-failure recovery message, in a subscription billing context in India.

Reference date (today): {reference_date}

Customer reply: "{reply}"

Classify the intent, resolve any relative date phrase (e.g. "kal", \
"naalaikku", "repu", "naale", "2 din mein") against the reference date \
into an ISO 8601 date, identify which code-mixed Indian language/script \
the reply is written in, and give your confidence.

If the reply is empty, a single word of acknowledgement, an emoji, or \
otherwise non-substantive, classify intent as "silence"."""

# Non-negotiation outcomes for promise_tracker, when the customer's reply
# does NOT amount to a clear, dated promise. clear_promise is handled
# separately (see promise_tracker_node) since its RecoveryOutcome row is
# deliberately deferred to Evaluation phase's promise-resolution step.
_INTENT_TO_RECOVERY_STATUS = {
    "vague_stall": "escalated",
    "dispute": "escalated",
    "silence": "failed",
}


class RecoveryState(TypedDict, total=False):
    db: Session
    event: FailureEvent
    failure_type: str
    valid: bool
    eligible_strategies: list[str]
    proposed_strategy: Optional[str]
    confidence: float
    policy_result: dict
    safety_result: dict
    final_decision: str
    customer_reply: dict
    recovery_outcome: dict


def _log_action(state: RecoveryState, node: str, output: dict, decision: str,
                 reasoning: str, confidence: Optional[float] = None,
                 idempotency_key: Optional[str] = None) -> None:
    db = state["db"]
    db.add(AgentAction(
        failure_event_id=state["event"].id,
        node=node,
        output=output,
        decision=decision,
        reasoning=reasoning,
        confidence=confidence,
        idempotency_key=idempotency_key,
    ))
    db.flush()  # visible to later nodes' queries within the same transaction


def detector_node(state: RecoveryState) -> RecoveryState:
    result = detect(state["event"])
    _log_action(
        state, "detector", {"failure_type": result["failure_type"]},
        "ALLOWED" if result["valid"] else "BLOCKED", result["reasoning"],
    )
    state["failure_type"] = result["failure_type"]
    state["valid"] = result["valid"]
    return state


def diagnosis_node(state: RecoveryState) -> RecoveryState:
    result = diagnose(state["failure_type"])
    _log_action(
        state, "diagnosis", {"eligible_strategies": result["eligible_strategies"]},
        "ALLOWED", result["reasoning"],
    )
    state["eligible_strategies"] = result["eligible_strategies"]
    return state


def strategy_agent_node(state: RecoveryState) -> RecoveryState:
    """Real LLM call: pick one strategy from diagnosis's eligible list.
    The model never sees or picks from the full strategy menu -- only the
    subset diagnosis already filtered to this failure_type, per the
    "AI judgment among constrained options" boundary (app/diagnosis.py).
    """
    eligible = state["eligible_strategies"]
    event = state["event"]

    if not eligible:
        # Nothing for the LLM to choose from -- don't spend an API call.
        # proposed_strategy stays None, which policy.py's
        # STRATEGY_NOT_ALLOWED rule will correctly catch and block.
        state["proposed_strategy"] = None
        state["confidence"] = 0.0
        _log_action(
            state, "strategy_agent", {"eligible_strategies": eligible},
            "BLOCKED", "No eligible strategies for this failure_type; nothing to choose.",
            confidence=0.0,
        )
        return state

    if len(eligible) == 1:
        # Only one option -- there's no real judgment call to make, so
        # don't spend an API call on it. This also sidesteps a real Groq
        # failure mode we hit in practice: forced-tool-call structured
        # output sometimes fails with "Tool choice is required, but model
        # did not call a tool" specifically when the model treats a
        # single-option "choice" as not worth a formal tool call, and
        # answers in free text instead. Since that happens at temperature=0,
        # it is deterministic -- retrying the same prompt does not help, so
        # avoiding the call altogether is the correct fix, not just a
        # workaround. See docs/what-broke.md, Entry 4.
        state["proposed_strategy"] = eligible[0]
        state["confidence"] = 1.0
        _log_action(
            state, "strategy_agent", {"strategy": eligible[0], "eligible_strategies": eligible},
            "ALLOWED", f"Only one eligible strategy for this failure_type ({eligible[0]}); "
                       f"selected without an LLM call.",
            confidence=1.0,
        )
        return state

    prompt = STRATEGY_PROMPT_TEMPLATE.format(
        failure_type=state["failure_type"],
        amount=event.amount,
        attempt_number=event.attempt_number,
        eligible_strategies=eligible,
    )
    decision = invoke_with_retry(strategy_llm(), prompt)

    state["proposed_strategy"] = decision.strategy
    state["confidence"] = decision.confidence
    _log_action(
        state, "strategy_agent",
        {"strategy": decision.strategy, "eligible_strategies": eligible},
        "ALLOWED", decision.reasoning, confidence=decision.confidence,
    )
    return state


def policy_node(state: RecoveryState) -> RecoveryState:
    result = check_policy(state["event"], state["proposed_strategy"], state["eligible_strategies"])
    _log_action(
        state, "policy", {"violations": result["violations"]},
        result["decision"], result["reasoning"],
    )
    state["policy_result"] = result
    return state


def safety_node(state: RecoveryState) -> RecoveryState:
    result = check_safety(state["db"], state["event"], state["policy_result"], state["confidence"])
    _log_action(
        state, "safety", {"reason": result.get("reason")}, result["decision"], result["reasoning"],
        confidence=state["confidence"], idempotency_key=result.get("idempotency_key"),
    )
    state["safety_result"] = result
    state["final_decision"] = result["decision"]
    return state


def executor_node(state: RecoveryState) -> RecoveryState:
    """Only reached when safety said ALLOWED. Five of the six strategies
    are immediate payment/action attempts, resolved the same way the
    baseline resolves them (mock_execute). negotiate_promise_to_pay is the
    exception: it sends a message and waits on a reply, so there's no
    payment outcome here yet -- that's promise_tracker's job next.
    """
    event = state["event"]
    strategy = state["proposed_strategy"]
    db = state["db"]

    if strategy == "negotiate_promise_to_pay":
        lang_code, bucket, reply_text = pick_customer_reply(str(event.id))
        state["customer_reply"] = {"language": lang_code, "bucket": bucket, "text": reply_text}
        _log_action(
            state, "executor",
            {"strategy": strategy, "action": "sent_negotiation_message"},
            "ALLOWED",
            f"Sent language-appropriate recovery message for event {event.id}; awaiting customer reply.",
        )
        return state

    outcome = mock_execute(
        event_id=str(event.id),
        attempt_number=event.attempt_number,
        already_recovered=(event.status == "recovered"),
        is_duplicate=False,
    )
    recovery_status = "recovered" if outcome == "SUCCESS" else "failed"
    recovered_amount = float(event.amount) if outcome == "SUCCESS" else None

    _log_action(
        state, "executor", {"strategy": strategy, "outcome": outcome},
        "ALLOWED", f"Executed strategy={strategy}, provider outcome={outcome}.",
    )
    db.add(RecoveryOutcome(
        failure_event_id=event.id,
        strategy=strategy,
        recovered_amount=recovered_amount,
        recovery_status=recovery_status,
        attempt_count=1,
        completed_at=datetime.now(timezone.utc),
    ))
    db.flush()
    state["recovery_outcome"] = {"recovery_status": recovery_status, "recovered_amount": recovered_amount}
    return state


def promise_tracker_node(state: RecoveryState) -> RecoveryState:
    """Real LLM call: extract intent + promised_date + detected_language
    from the simulated customer reply, in one call (see app/schemas.py).
    Only reached when executor sent a negotiate_promise_to_pay message.
    """
    event = state["event"]
    db = state["db"]
    reply = state["customer_reply"]

    reference_date = datetime.now(timezone.utc).date().isoformat()
    prompt = PROMISE_PROMPT_TEMPLATE.format(reference_date=reference_date, reply=reply["text"])
    extraction = invoke_with_retry(promise_llm(), prompt)

    _log_action(
        state, "promise_tracker",
        {
            "intent": extraction.intent,
            "detected_language": extraction.detected_language,
            "promised_date": extraction.promised_date,
            "customer_reply": reply["text"],
        },
        "ALLOWED",
        f"Extracted intent={extraction.intent} from customer reply.",
        confidence=extraction.confidence,
    )

    if extraction.intent == "clear_promise" and extraction.promised_date:
        db.add(Commitment(
            failure_event_id=event.id,
            promised_date=datetime.fromisoformat(extraction.promised_date).date(),
            status="pending",
            extracted_from_message=reply["text"],
        ))
        # Deliberately NOT writing a recovery_outcomes row here: the money
        # hasn't arrived yet, only a promise has. Evaluation phase's
        # promise-resolution script owns updating commitments.status to
        # kept/broken and writing the eventual RecoveryOutcome once that's
        # known. This is a deferred-outcome design decision made during
        # LLM Integration phase wiring -- flagged here as the load-bearing
        # comment for anyone building the Evaluation phase eval script.
        state["recovery_outcome"] = {"recovery_status": "pending_commitment", "recovered_amount": None}
    else:
        recovery_status = _INTENT_TO_RECOVERY_STATUS[extraction.intent]
        db.add(RecoveryOutcome(
            failure_event_id=event.id,
            strategy="negotiate_promise_to_pay",
            recovered_amount=None,
            recovery_status=recovery_status,
            attempt_count=1,
            completed_at=datetime.now(timezone.utc),
        ))
        state["recovery_outcome"] = {"recovery_status": recovery_status, "recovered_amount": None}

    db.flush()
    return state


def _route_after_safety(state: RecoveryState) -> str:
    return "executor" if state["final_decision"] == "ALLOWED" else END


def _route_after_executor(state: RecoveryState) -> str:
    return "promise_tracker" if state.get("proposed_strategy") == "negotiate_promise_to_pay" else END


def build_graph():
    graph = StateGraph(RecoveryState)
    graph.add_node("detector", detector_node)
    graph.add_node("diagnosis", diagnosis_node)
    graph.add_node("strategy_agent", strategy_agent_node)
    graph.add_node("policy", policy_node)
    graph.add_node("safety", safety_node)
    graph.add_node("executor", executor_node)
    graph.add_node("promise_tracker", promise_tracker_node)

    graph.set_entry_point("detector")
    graph.add_edge("detector", "diagnosis")
    graph.add_edge("diagnosis", "strategy_agent")
    graph.add_edge("strategy_agent", "policy")
    graph.add_edge("policy", "safety")

    graph.add_conditional_edges(
        "safety", _route_after_safety, {"executor": "executor", END: END},
    )
    graph.add_conditional_edges(
        "executor", _route_after_executor, {"promise_tracker": "promise_tracker", END: END},
    )
    graph.add_edge("promise_tracker", END)

    return graph.compile()


app_graph = build_graph()


def run_event(db: Session, event: FailureEvent) -> RecoveryState:
    """Run one failure_event through the full LLM Integration phase graph.
    Caller owns the session lifecycle (commit/rollback) -- this function
    only flushes so later nodes can see earlier writes within the same
    transaction.

    NOTE: this now makes real Groq API calls (strategy_agent always;
    promise_tracker only when negotiate_promise_to_pay is chosen). Requires
    GROQ_API_KEY to be set and network access to api.groq.com.
    """
    initial_state: RecoveryState = {"db": db, "event": event}
    return app_graph.invoke(initial_state)

