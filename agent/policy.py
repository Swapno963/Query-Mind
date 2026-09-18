from __future__ import annotations

from typing import Any

from agent.operation import READ, WRITE_OPERATIONS, OPERATIONS


def decide(operation: str | None) -> dict[str, Any]:
    op = str(operation or "").upper()
    if op == READ:
        return {
            "operation": READ,
            "sql_allowed": True,
            "mcp_allowed": True,
            "mcp_required": False,
        }
    if op in WRITE_OPERATIONS:
        return {
            "operation": op,
            "sql_allowed": False,
            "mcp_allowed": True,
            "mcp_required": True,
        }
    return {
        "operation": op or None,
        "sql_allowed": False,
        "mcp_allowed": False,
        "mcp_required": False,
    }


def resolve_mode(
    *,
    operation: str | None,
    mcp_capable: bool,
    mcp_available: bool,
) -> str:
    """Return mcp, sql, or deny. Never sql for writes."""
    policy = decide(operation)
    op = policy["operation"]
    if op not in OPERATIONS:
        return "deny"
    if policy["mcp_required"]:
        if mcp_available and mcp_capable:
            return "mcp"
        return "deny"
    if mcp_available and mcp_capable:
        return "mcp"
    if policy["sql_allowed"]:
        return "sql"
    return "deny"
