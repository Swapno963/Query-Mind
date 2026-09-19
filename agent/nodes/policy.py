from typing import Any

from agent.policy import decide
from agent.state import QueryMindState


def policy_check(state: QueryMindState) -> dict[str, Any]:
    intent = state.operation_intent or {}
    surface = getattr(state, "product_surface", "") or ""
    policy = decide(intent.get("operation"), product_surface=surface)
    routing = {
        **(state.routing or {}),
        "operation": policy["operation"],
        "sql_allowed": policy["sql_allowed"],
        "mcp_required": policy["mcp_required"],
        "tool": None,
        "sql_fallback": False,
        "reason": "policy",
    }
    if not policy["sql_allowed"] and not policy["mcp_allowed"]:
        return {
            "execution_mode": "deny",
            "answer_kind": "unsupported_operation",
            "routing": {**routing, "mode": "deny", "reason": "unsupported_operation"},
            "current_node": "policy_check",
            "status": "failed",
        }
    return {
        "routing": {**routing, "mode": None},
        "current_node": "policy_check",
        "status": "running",
    }
