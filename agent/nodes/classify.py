from typing import Any

from agent.operation import extract_operation
from agent.state import QueryMindState


def classify_operation(state: QueryMindState) -> dict[str, Any]:
    intent = extract_operation(
        state.question,
        state.conversation_context,
        use_llm=True,
    )
    if not intent.get("valid"):
        reason = intent.get("reason") or "needs_clarification"
        kind = "needs_clarification" if reason == "needs_clarification" else "unsupported_operation"
        return {
            "operation_intent": intent,
            "execution_mode": "clarify" if kind == "needs_clarification" else "deny",
            "answer_kind": kind,
            "database_error": reason,
            "routing": {
                "operation": intent.get("operation"),
                "mode": "clarify" if kind == "needs_clarification" else "deny",
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
