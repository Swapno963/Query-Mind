from typing import Any

from agent.mcp.client import MCPClientError, call_tool, result_to_rows
from agent.mcp.redact import redact
from agent.state import QueryMindState


def mcp_execute(state: QueryMindState) -> dict[str, Any]:
    url = (state.mcp_server_url or "").strip()
    selected = state.mcp_result or {}
    tool = selected.get("tool") or (state.routing or {}).get("tool")
    arguments = selected.get("arguments") or {}
    routing = dict(state.routing or {})
    if not url or not tool:
        return {
            "execution_mode": "deny",
            "execution_result": {
                "success": False,
                "rows": [],
                "columns": [],
                "row_count": 0,
                "kind": "mcp_failed",
            },
            "answer_kind": "mcp_failed",
            "database_error": "No MCP tool was selected.",
            "routing": {**routing, "mode": "deny", "reason": "mcp_failed"},
            "current_node": "mcp_execute",
            "status": "failed",
        }
    try:
        raw = call_tool(url, str(tool), arguments)
        rows = result_to_rows(raw)
        columns = list(rows[0].keys()) if rows else []
        return {
            "execution_result": {
                "success": True,
                "rows": rows,
                "columns": columns,
                "row_count": len(rows),
                "kind": "zero_rows" if not rows else "success",
            },
            "answer_kind": "zero_rows" if not rows else "success",
            "routing": {**routing, "mode": "mcp", "reason": "mcp_executed"},
            "current_node": "mcp_execute",
            "status": "running",
        }
    except MCPClientError as exc:
        return {
            "execution_mode": "deny",
            "execution_result": {
                "success": False,
                "rows": [],
                "columns": [],
                "row_count": 0,
                "kind": "mcp_failed",
            },
            "answer_kind": "mcp_failed",
            "database_error": exc.message,
            "routing": {
                **routing,
                "mode": "deny",
                "reason": "mcp_failed",
                "error": redact({"detail": exc.detail}),
            },
            "current_node": "mcp_execute",
            "status": "failed",
        }
