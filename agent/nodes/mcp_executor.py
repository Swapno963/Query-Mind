from typing import Any
import logging

from agent.mcp.client import MCP_SOFT_STATUSES, MCPClientError, call_tool, result_to_rows
from agent.mcp.redact import redact
from agent.state import QueryMindState

logger = logging.getLogger("querymind.mcp")


def _is_envelope(row: Any) -> bool:
    return isinstance(row, dict) and bool(row.get("status")) and (
        row.get("message") is not None or "ok" in row
    )


def _without_confirmation(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(arguments or {}).items()
        if str(key).lower().replace("-", "_") not in {"confirmed", "confirmation_id"}
    }


def _invoke(url: str, tool: str, arguments: dict[str, Any], headers) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    raw = call_tool(url, str(tool), arguments, headers)
    rows = result_to_rows(raw)
    envelope = rows[0] if rows and _is_envelope(rows[0]) else None
    return rows, envelope


def mcp_execute(state: QueryMindState) -> dict[str, Any]:
    url = (state.mcp_server_url or "").strip()
    selected = state.mcp_result or {}
    tool = selected.get("tool") or (state.routing or {}).get("tool")
    arguments = _without_confirmation(selected.get("arguments") or {})
    routing = dict(state.routing or {})
    headers = getattr(state, "mcp_headers", None)
    failed = {
        "execution_mode": "deny",
        "execution_result": {
            "success": False,
            "rows": [],
            "columns": [],
            "row_count": 0,
            "kind": "mcp_failed",
        },
        "answer_kind": "mcp_failed",
        "routing": {**routing, "mode": "deny", "reason": "mcp_failed"},
        "current_node": "mcp_execute",
        "status": "failed",
    }
    if not url or not tool:
        logger.warning("mcp execute skipped url=%r tool=%r", url, tool)
        return {**failed, "database_error": "No MCP tool was selected."}
    try:
        retried_confirmation = False
        rows, envelope = _invoke(url, str(tool), arguments, headers)
        if envelope is not None and str(envelope.get("status") or "") == "needs_confirmation":
            token = str(envelope.get("confirmation_id") or "").strip()
            if token:
                logger.info("mcp confirming tool=%s", tool)
                retried_confirmation = True
                rows, envelope = _invoke(
                    url,
                    str(tool),
                    {**arguments, "confirmed": True, "confirmation_id": token},
                    headers,
                )
        if envelope is not None:
            status = str(envelope.get("status") or "")
            if retried_confirmation and envelope.get("ok") is not True:
                logger.warning(
                    "mcp confirmation retry failed tool=%s status=%s",
                    tool,
                    status or "error",
                )
                return {
                    **failed,
                    "execution_result": {
                        **failed["execution_result"],
                        "rows": rows,
                        "columns": list(rows[0].keys()) if rows else [],
                        "row_count": len(rows),
                    },
                    "database_error": str(
                        envelope.get("message") or "MCP write could not be confirmed."
                    ),
                    "routing": {
                        **failed["routing"],
                        "error": redact({"status": status, "ok": envelope.get("ok")}),
                    },
                }
            if envelope.get("ok") is False and status not in MCP_SOFT_STATUSES:
                logger.warning(
                    "mcp execute rejected tool=%s status=%s",
                    tool,
                    status or "error",
                )
                return {
                    **failed,
                    "execution_result": {
                        **failed["execution_result"],
                        "rows": rows,
                        "columns": list(rows[0].keys()) if rows else [],
                        "row_count": len(rows),
                    },
                    "database_error": str(envelope.get("message") or "MCP tool returned an error."),
                    "routing": {
                        **failed["routing"],
                        "error": redact({"status": status, "ok": envelope.get("ok")}),
                    },
                }
            if status in MCP_SOFT_STATUSES:
                kind = status
            elif envelope.get("ok") is True and not envelope.get("data"):
                kind = "zero_rows"
            else:
                kind = str(status or "success")
            return {
                "execution_result": {
                    "success": True,
                    "rows": rows,
                    "columns": list(rows[0].keys()),
                    "row_count": len(rows),
                    "kind": kind,
                },
                "answer_kind": kind,
                "routing": {**routing, "mode": "mcp", "reason": "mcp_executed"},
                "current_node": "mcp_execute",
                "status": "running",
            }
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
        logger.warning(
            "mcp execute failed tool=%s error=%s detail=%s",
            tool,
            exc.message,
            redact({"detail": exc.detail}),
        )
        return {
            **failed,
            "database_error": exc.message,
            "routing": {
                **failed["routing"],
                "error": redact({"detail": exc.detail}),
            },
        }
