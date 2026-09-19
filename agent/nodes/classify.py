from typing import Any

from agent.operation import (
    WRITE_OPERATIONS,
    classify_request_kind,
    extract_operation,
    mutation_verb_operation,
)
from agent.state import QueryMindState


def classify_operation(state: QueryMindState) -> dict[str, Any]:
    backend = getattr(state, "llm_backend", "local") or "local"
    surface = getattr(state, "product_surface", "") or ""
    kind = classify_request_kind(
        state.question,
        use_llm=True,
        backend=backend,
    )
    if kind == "conversation":
        return {
            "operation_intent": {
                "valid": True,
                "operation": None,
                "resource": None,
                "action": None,
                "parameters": {},
                "query_features": [],
                "reason": "conversation",
            },
            "execution_mode": "converse",
            "answer_kind": "conversation",
            "routing": {
                "operation": None,
                "mode": "converse",
                "tool": None,
                "sql_fallback": False,
                "reason": "conversation",
            },
            "current_node": "classify_operation",
            "status": "running",
        }

    write_op = mutation_verb_operation(state.question)
    if surface == "chat" and write_op in WRITE_OPERATIONS:
        return {
            "operation_intent": {
                "valid": False,
                "operation": write_op,
                "reason": "chat_read_only",
            },
            "execution_mode": "deny",
            "answer_kind": "unsupported_operation",
            "database_error": "unsupported_operation",
            "routing": {
                "operation": write_op,
                "mode": "deny",
                "tool": None,
                "sql_fallback": False,
                "reason": "chat_read_only",
            },
            "current_node": "classify_operation",
            "status": "failed",
        }

    intent = extract_operation(
        state.question,
        state.conversation_context,
        use_llm=True,
        backend=backend,
    )
    if surface == "chat" and (intent.get("operation") or "") in WRITE_OPERATIONS:
        return {
            "operation_intent": intent,
            "execution_mode": "deny",
            "answer_kind": "unsupported_operation",
            "database_error": "unsupported_operation",
            "routing": {
                "operation": intent.get("operation"),
                "mode": "deny",
                "tool": None,
                "sql_fallback": False,
                "reason": "chat_read_only",
            },
            "current_node": "classify_operation",
            "status": "failed",
        }
    if not intent.get("valid"):
        reason = intent.get("reason") or "needs_clarification"
        answer_kind = (
            "needs_clarification" if reason == "needs_clarification" else "unsupported_operation"
        )
        return {
            "operation_intent": intent,
            "execution_mode": "clarify" if answer_kind == "needs_clarification" else "deny",
            "answer_kind": answer_kind,
            "database_error": reason,
            "routing": {
                "operation": intent.get("operation"),
                "mode": "clarify" if answer_kind == "needs_clarification" else "deny",
                "tool": None,
                "sql_fallback": False,
                "reason": reason,
            },
            "current_node": "classify_operation",
            "status": "failed",
        }
    return {
        "operation_intent": intent,
        "current_node": "classify_operation",
        "status": "running",
    }
