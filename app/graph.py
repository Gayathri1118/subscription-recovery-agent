"""LangGraph state machine — Day 2 scope: detector -> diagnosis -> policy -> safety.

No LLM calls in this graph yet. Day 3 adds a `strategy_agent` node between
`diagnosis` and `policy` (replacing the placeholder proposed_strategy set
here), and `executor` + `promise_tracker` nodes after `safety`.

Every node writes exactly one row to `agent_actions`, so the graph run for
any event is fully reconstructable from the audit trail alone.
"""
from typing import TypedDict, Optional

from langgraph.graph import StateGraph, END
from sqlalchemy.orm import Session

from app.detector import detect
from app.diagnosis import diagnose
from app.policy import check_policy
from app.safety import check_safety
from app.models import AgentAction, FailureEvent


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

    # Day 2 placeholder — no strategy_agent node exists yet, so deterministically
    # propose the first eligible strategy. Day 3 replaces these two lines with
    # the real LLM call's output (strategy + confidence).
    state["proposed_strategy"] = result["eligible_strategies"][0] if result["eligible_strategies"] else None
    state["confidence"] = 1.0  # TODO Day 3: replace with strategy_agent.confidence

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


def build_graph():
    graph = StateGraph(RecoveryState)
    graph.add_node("detector", detector_node)
    graph.add_node("diagnosis", diagnosis_node)
    graph.add_node("policy", policy_node)
    graph.add_node("safety", safety_node)

    graph.set_entry_point("detector")
    graph.add_edge("detector", "diagnosis")
    graph.add_edge("diagnosis", "policy")
    graph.add_edge("policy", "safety")
    graph.add_edge("safety", END)

    return graph.compile()


app_graph = build_graph()


def run_event(db: Session, event: FailureEvent) -> RecoveryState:
    """Run one failure_event through the Day 2 graph. Caller owns the
    session lifecycle (commit/rollback) — this function only flushes so
    later nodes can see earlier writes within the same transaction.
    """
    initial_state: RecoveryState = {"db": db, "event": event}
    return app_graph.invoke(initial_state)
