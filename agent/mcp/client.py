from __future__ import annotations

import asyncio
from typing import Any


class MCPClientError(Exception):
    def __init__(self, message: str, *, detail: str = ""):
        super().__init__(message)
        self.message = message
        self.detail = detail


def _run(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise MCPClientError("MCP calls cannot run inside an existing event loop.")


def _tool_to_dict(tool: Any) -> dict[str, Any]:
    schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None)
    if hasattr(schema, "model_dump"):
        schema = schema.model_dump(mode="python")
    elif hasattr(schema, "dict"):
        schema = schema.dict()
    return {
        "name": getattr(tool, "name", "") or "",
        "description": getattr(tool, "description", "") or "",
        "inputSchema": schema or {"type": "object", "properties": {}},
    }


async def _list_tools(url: str) -> list[dict[str, Any]]:
    from mcp import Client

    async with Client(url) as client:
        result = await client.list_tools()
    tools = getattr(result, "tools", None) or []
    return [_tool_to_dict(tool) for tool in tools]


async def _call_tool(url: str, name: str, arguments: dict[str, Any] | None) -> Any:
    from mcp import Client

    async with Client(url) as client:
        return await client.call_tool(name, arguments or {})


def list_tools(url: str) -> list[dict[str, Any]]:
    if not url:
        return []
    try:
        return _run(_list_tools(url))
    except MCPClientError:
        raise
    except Exception as exc:
        raise MCPClientError("Could not list MCP tools.", detail=str(exc)) from exc


def call_tool(url: str, name: str, arguments: dict[str, Any] | None) -> Any:
    if not url:
        raise MCPClientError("No MCP server is configured.")
    try:
        return _run(_call_tool(url, name, arguments or {}))
    except MCPClientError:
        raise
    except Exception as exc:
        raise MCPClientError("MCP tool call failed.", detail=str(exc)) from exc


def result_to_rows(result: Any) -> list[dict[str, Any]]:
    structured = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
    if isinstance(structured, list):
        return [item if isinstance(item, dict) else {"value": item} for item in structured]
    if isinstance(structured, dict):
        if isinstance(structured.get("rows"), list):
            return [
                item if isinstance(item, dict) else {"value": item}
                for item in structured["rows"]
            ]
        return [structured]
    rows: list[dict[str, Any]] = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if text:
            rows.append({"result": text})
            continue
        data = getattr(item, "data", None)
        if data is not None:
            rows.append(data if isinstance(data, dict) else {"value": data})
    if getattr(result, "isError", False) or getattr(result, "is_error", False):
        raise MCPClientError(
            "MCP tool returned an error.",
            detail=str(rows[0].get("result") if rows else ""),
        )
    return rows or [{"result": "ok"}]
