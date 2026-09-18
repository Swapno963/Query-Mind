from typing import Any

from agent.mcp.capabilities import first_matching_tool
from agent.mcp.client import MCPClientError, list_tools
from agent.mcp.redact import redact
from agent.policy import decide, resolve_mode
from agent.state import QueryMindState


def capability_resolve(
    state: QueryMindState,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    intent = state.operation_intent or {}
    policy = decide(intent.get("operation"))
    url = (state.mcp_server_url or "").strip()
    list_error = ""
    listed = tools
    provided = tools is not None
    if listed is None:
        if url:
            try:
                listed = list_tools(url)
            except MCPClientError as exc:
                listed = []
                list_error = exc.message
        else:
            listed = []

    match = first_matching_tool(intent, listed or [])
    mcp_capable = bool(match and match.get("ok"))
    if provided:
        mcp_available = True
    elif list_error:
        mcp_available = False
    else:
        mcp_available = bool(url)

    mode = resolve_mode(
        operation=intent.get("operation"),
        mcp_capable=mcp_capable,
        mcp_available=mcp_available,
    )
    if mode == "mcp":
        reason = (match or {}).get("reason") or "mcp"
    elif mode == "sql":
        reason = "mcp_cannot_satisfy"
    else:
        reason = list_error or "no_suitable_mcp_capability"

    routing = {
        "operation": policy["operation"],
        "mode": mode,
        "tool": (match or {}).get("tool"),
        "sql_fallback": mode == "sql",
        "reason": reason,
        "sql_allowed": policy["sql_allowed"],
        "mcp_required": policy["mcp_required"],
        "arguments": redact((match or {}).get("arguments") or {}),
    }
    payload: dict[str, Any] = {
        "execution_mode": mode,
        "routing": routing,
        "current_node": "capability_resolve",
        "status": "running" if mode in {"mcp", "sql"} else "failed",
    }
    if match:
        payload["mcp_result"] = {
            "tool": match.get("tool"),
            "arguments": match.get("arguments") or {},
        }
    if mode == "deny":
        payload["answer_kind"] = "unsupported_operation"
        payload["database_error"] = reason
    return payload
