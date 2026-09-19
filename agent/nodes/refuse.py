from typing import Any

from ..state import QueryMindState

REFUSAL_MESSAGES = {
    "unavailable": (
        "QueryMind could not read that from your allowed tables. "
        "If this should be included, change access from Your data."
    ),
    "no_allow_list": (
        "QueryMind will not run questions until you choose which tables it may use."
    ),
    "invalid_sql": (
        "QueryMind could not safely answer from your allowed tables. "
        "Try rephrasing the question."
    ),
    "connection_failed": (
        "QueryMind could not connect to your database. Check the connection from Your data."
    ),
    "needs_clarification": (
        "QueryMind needs a clearer lookup. Ask what you want to see from the tables you allowed."
    ),
    "needs_parameters": (
        "QueryMind needs a bit more information before it can continue."
    ),
    "unsupported_operation": (
        "QueryMind cannot perform that operation. Writes must use a configured MCP tool; SQL cannot change data."
    ),
    "chat_read_only": (
        "QueryMind chat can only look up data. It cannot create, update, or delete records."
    ),
    "mcp_failed": (
        "QueryMind could not complete that operation through MCP. It will not fall back to SQL for writes."
    ),
    "error": (
        "QueryMind could not finish this answer. It will not invent database results."
    ),
}


def refuse_answer(state: QueryMindState) -> dict[str, Any]:
    kind = (
        (state.validation_result or {}).get("kind")
        or state.answer_kind
        or "unavailable"
    )
    if kind == "no_allow_list":
        kind = "unavailable"
    surface = getattr(state, "product_surface", "") or ""
    routing_reason = (state.routing or {}).get("reason") or ""
    if surface == "chat" and (
        kind == "unsupported_operation" or routing_reason in {"chat_read_only", "unsupported_operation"}
    ):
        message = REFUSAL_MESSAGES["chat_read_only"]
        kind = "unsupported_operation"
    else:
        message = REFUSAL_MESSAGES.get(kind, REFUSAL_MESSAGES["unavailable"])
    if kind == "needs_parameters":
        missing = (state.routing or {}).get("missing") or []
        if missing:
            pretty = ", ".join(str(item).replace("_", " ") for item in missing)
            message = f"I still need: {pretty}."
    detail = state.validation_error or state.database_error
    return {
        "final_answer": message,
        "answer_kind": kind,
        "error_analysis": {
            **(state.error_analysis or {}),
            "detail": detail,
            "action": "end",
        },
        "current_node": "refuse",
        "status": "completed",
    }
