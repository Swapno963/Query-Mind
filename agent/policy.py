from __future__ import annotations

from typing import Any

from agent.operation import READ, WRITE_OPERATIONS, OPERATIONS


def decide(operation: str | None, *, product_surface: str = "") -> dict[str, Any]:
    op = str(operation or "").upper()
    if op == READ:
        return {
            "operation": READ,
            "sql_allowed": True,
            "mcp_allowed": True,
            "mcp_required": False,
        }
    if op in WRITE_OPERATIONS:
        if product_surface == "api":
            return {
                "operation": op,
                "sql_allowed": False,
                "mcp_allowed": True,
                "mcp_required": True,
            }
        return {
            "operation": op,
            "sql_allowed": False,
            "mcp_allowed": False,
            "mcp_required": False,
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
    sql_available: bool = True,
    product_surface: str = "",
) -> str:
    """Return mcp, sql, or deny. Never sql for writes. Chat never writes."""
    policy = decide(operation, product_surface=product_surface)
    op = policy["operation"]
    if op not in OPERATIONS:
        return "deny"
    if policy["mcp_required"]:
        if mcp_available and mcp_capable and policy["mcp_allowed"]:
            return "mcp"
        return "deny"
    if policy["mcp_allowed"] and mcp_available and mcp_capable:
        return "mcp"
    if policy["sql_allowed"] and sql_available:
        return "sql"
    return "deny"
