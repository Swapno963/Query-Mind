from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from agent.mcp.redact import redact

logger = logging.getLogger("querymind.mcp")

MCP_SOFT_STATUSES = {"needs_confirmation", "needs_parameters", "ambiguous"}
DEFAULT_MCP_TIMEOUT_SECONDS = 30.0


class MCPClientError(Exception):
    def __init__(self, message: str, *, detail: str = ""):
        super().__init__(message)
        self.message = message
        self.detail = detail


def mcp_timeout_seconds() -> float:
    try:
        from django.conf import settings

        value = getattr(settings, "MCP_TIMEOUT_SECONDS", DEFAULT_MCP_TIMEOUT_SECONDS)
        timeout = float(value)
    except Exception:
        timeout = DEFAULT_MCP_TIMEOUT_SECONDS
    return timeout if timeout > 0 else DEFAULT_MCP_TIMEOUT_SECONDS


def _run(coro):
    async def wrapped():
        try:
            return await asyncio.wait_for(coro, timeout=mcp_timeout_seconds())
        except asyncio.TimeoutError as exc:
            raise MCPClientError("MCP request timed out.") from exc

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(wrapped())
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


def _clean_headers(headers: dict[str, str] | None) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, value in (headers or {}).items():
        if value:
            cleaned[str(key)] = str(value)
    return cleaned


async def _with_client(url: str, headers: dict[str, str] | None, callback):
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    clean = _clean_headers(headers)
    if not clean:
        async with Client(url) as client:
            return await callback(client)
    http = create_mcp_http_client(headers=clean)
    async with http:
        async with Client(streamable_http_client(url, http_client=http)) as client:
            return await callback(client)


async def _list_tools(url: str, headers: dict[str, str] | None = None) -> list[dict[str, Any]]:
    async def callback(client):
        result = await client.list_tools()
        tools = getattr(result, "tools", None) or []
        return [_tool_to_dict(tool) for tool in tools]

    return await _with_client(url, headers, callback)


async def _call_tool(
    url: str,
    name: str,
    arguments: dict[str, Any] | None,
    headers: dict[str, str] | None = None,
) -> Any:
    async def callback(client):
        return await client.call_tool(name, arguments or {})

    return await _with_client(url, headers, callback)


def list_tools(url: str, headers: dict[str, str] | None = None) -> list[dict[str, Any]]:
    if not url:
        return []
    try:
        tools = _run(_list_tools(url, headers))
        logger.info("mcp list_tools url=%s count=%s names=%s", url, len(tools), [item.get("name") for item in tools])
        return tools
    except MCPClientError:
        raise
    except Exception as exc:
        logger.warning("mcp list_tools failed url=%s error=%s", url, redact({"detail": str(exc)}))
        raise MCPClientError("Could not list MCP tools.", detail=str(exc)) from exc


def call_tool(
    url: str,
    name: str,
    arguments: dict[str, Any] | None,
    headers: dict[str, str] | None = None,
) -> Any:
    if not url:
        raise MCPClientError("No MCP server is configured.")
    try:
        logger.info("mcp call_tool url=%s name=%s arguments=%s", url, name, redact(arguments or {}))
        result = _run(_call_tool(url, name, arguments or {}, headers))
        logger.info(
            "mcp call_tool ok url=%s name=%s is_error=%s",
            url,
            name,
            getattr(result, "isError", None) or getattr(result, "is_error", None),
        )
        return result
    except MCPClientError:
        raise
    except Exception as exc:
        logger.warning("mcp call_tool failed url=%s name=%s error=%s", url, name, redact({"detail": str(exc)}))
        raise MCPClientError("MCP tool call failed.", detail=str(exc)) from exc


def result_to_rows(result: Any) -> list[dict[str, Any]]:
    structured = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
    if isinstance(structured, list):
        rows = [item if isinstance(item, dict) else {"value": item} for item in structured]
        return _require_rows(result, rows)
    if isinstance(structured, dict):
        if isinstance(structured.get("rows"), list):
            rows = [
                item if isinstance(item, dict) else {"value": item}
                for item in structured["rows"]
            ]
            return _require_rows(result, rows)
        return [structured]
    rows: list[dict[str, Any]] = []
    malformed = False
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if text:
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = None
                malformed = True
            if isinstance(parsed, dict):
                rows.append(parsed)
            elif isinstance(parsed, list):
                rows.extend(
                    entry if isinstance(entry, dict) else {"value": entry}
                    for entry in parsed
                )
            else:
                malformed = True
            continue
        data = getattr(item, "data", None)
        if data is not None:
            rows.append(data if isinstance(data, dict) else {"value": data})
    if getattr(result, "isError", False) or getattr(result, "is_error", False):
        status = rows[0].get("status") if rows else ""
        if status not in MCP_SOFT_STATUSES:
            raise MCPClientError(
                "MCP tool returned an error.",
                detail=str(rows[0].get("result") if rows else ""),
            )
    if not rows:
        if malformed:
            raise MCPClientError("MCP tool returned a malformed result.")
        raise MCPClientError("MCP tool returned an empty result.")
    return rows


def _require_rows(result: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if rows:
        return rows
    if getattr(result, "isError", False) or getattr(result, "is_error", False):
        raise MCPClientError("MCP tool returned an error.")
    raise MCPClientError("MCP tool returned an empty result.")


def redacted_headers(headers: dict[str, str] | None) -> dict[str, str]:
    return redact(_clean_headers(headers))
