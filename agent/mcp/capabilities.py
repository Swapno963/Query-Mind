from __future__ import annotations

from typing import Any

from agent.mcp.redact import redact
from agent.operation import (
    ACTION,
    CREATE,
    DELETE,
    IGNORED_PARAMS,
    PARAM_ALIASES,
    READ,
    UPDATE,
    _singular,
)


AGGREGATION_PARAMS = {
    "aggregation",
    "aggregate",
    "metric",
    "group_by",
    "groupby",
    "having",
}
JOIN_PARAMS = {"join", "include", "expand", "with"}


def infer_operation(name: str, description: str = "") -> str | None:
    text = f"{name} {description}".lower().replace("-", "_")
    if any(token in text for token in ("delete", "remove")):
        return DELETE
    if any(token in text for token in ("create", "insert", "add_")):
        return CREATE
    if any(token in text for token in ("update", "set_", "mark", "change", "patch")):
        return UPDATE
    if any(token in text for token in ("cancel", "refund", "ship", "fulfill", "approve")):
        return ACTION
    if any(token in text for token in ("get", "list", "read", "find", "search", "fetch", "show")):
        return READ
    return None


def infer_resource(name: str, description: str = "") -> str | None:
    combined = f"{name} {description}".lower().replace("-", "_")
    for token in (
        "order",
        "customer",
        "product",
        "user",
        "item",
        "invoice",
        "category",
        "restaurant",
        "menu",
    ):
        if token in combined:
            return token
    parts = [part for part in name.lower().replace("-", "_").split("_") if part]
    skip = {
        "get",
        "list",
        "read",
        "find",
        "search",
        "fetch",
        "show",
        "create",
        "update",
        "delete",
        "remove",
        "set",
        "mark",
        "change",
        "cancel",
    }
    leftovers = [part for part in parts if part not in skip]
    if leftovers:
        return _singular(leftovers[-1])
    return None


def schema_properties(tool: dict[str, Any]) -> dict[str, Any]:
    schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    if not isinstance(schema, dict):
        return {}
    properties = schema.get("properties") or {}
    return properties if isinstance(properties, dict) else {}


def schema_property_names(tool: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for key in schema_properties(tool):
        names.add(str(key).lower())
        names.add(PARAM_ALIASES.get(str(key).lower().replace("-", "_"), str(key).lower()))
    return names


def capability_from_tool(tool: dict[str, Any]) -> dict[str, Any]:
    name = str(tool.get("name") or "")
    description = str(tool.get("description") or "")
    return {
        "tool": name,
        "operation": infer_operation(name, description),
        "resource": infer_resource(name, description),
        "parameters": sorted(schema_property_names(tool)),
        "constraints": {
            "aggregation": bool(schema_property_names(tool) & AGGREGATION_PARAMS),
            "join": bool(schema_property_names(tool) & JOIN_PARAMS),
        },
    }


def bind_arguments(intent: dict[str, Any], tool: dict[str, Any]) -> dict[str, Any]:
    properties = schema_properties(tool)
    params = dict(intent.get("parameters") or {})
    bound: dict[str, Any] = {}
    for prop in properties:
        key = str(prop)
        lowered = key.lower().replace("-", "_")
        if lowered in IGNORED_PARAMS or PARAM_ALIASES.get(lowered, lowered) in IGNORED_PARAMS:
            continue
        alias = PARAM_ALIASES.get(lowered, lowered)
        if key in params:
            bound[key] = params[key]
        elif lowered in params:
            bound[key] = params[lowered]
        elif alias in params:
            bound[key] = params[alias]
        elif alias == "order_id" and "id" in params and "order" in (intent.get("resource") or ""):
            bound[key] = params["id"]
    return bound


def _required_fields(tool: dict[str, Any]) -> list[str]:
    schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    if not isinstance(schema, dict):
        return []
    required = schema.get("required") or []
    return [str(item) for item in required] if isinstance(required, list) else []


def tool_satisfies(intent: dict[str, Any], tool: dict[str, Any]) -> dict[str, Any]:
    capability = capability_from_tool(tool)
    operation = str(intent.get("operation") or "").upper()
    if capability["operation"] != operation:
        return {"ok": False, "reason": "operation_mismatch", "tool": tool.get("name")}
    intent_resource = _singular(str(intent.get("resource") or ""))
    tool_resource = _singular(str(capability.get("resource") or ""))
    properties = schema_property_names(tool)
    if intent_resource and tool_resource and intent_resource != tool_resource:
        aliases = {"menu": "item", "menuitem": "item", "menu_item": "item"}
        if aliases.get(intent_resource, intent_resource) != aliases.get(tool_resource, tool_resource):
            if "resource" not in properties:
                return {"ok": False, "reason": "resource_mismatch", "tool": tool.get("name")}
    features = {str(item).lower() for item in (intent.get("query_features") or [])}
    if "aggregation" in features and not capability["constraints"]["aggregation"]:
        return {"ok": False, "reason": "aggregation_unsupported", "tool": tool.get("name")}
    if "join" in features and not capability["constraints"]["join"]:
        return {"ok": False, "reason": "join_unsupported", "tool": tool.get("name")}
    if "group" in features and not capability["constraints"]["aggregation"]:
        return {"ok": False, "reason": "group_unsupported", "tool": tool.get("name")}
    if "unbounded_filter" in features and not (
        properties & {"filter", "query", "q", "search", "where"}
    ):
        return {"ok": False, "reason": "filter_unsupported", "tool": tool.get("name")}
    bound = bind_arguments(intent, tool)
    missing = [
        field
        for field in _required_fields(tool)
        if bound.get(field) in (None, "")
    ]
    result = {
        "tool": tool.get("name"),
        "arguments": bound,
        "capability": redact(capability),
        "missing": missing,
    }
    if missing:
        return {**result, "ok": False, "reason": "missing_parameters"}
    return {**result, "ok": True, "reason": "schema_match"}


def first_matching_tool(
    intent: dict[str, Any],
    tools: list[dict[str, Any]],
) -> dict[str, Any] | None:
    missing_match = None
    for tool in tools or []:
        result = tool_satisfies(intent, tool)
        if result.get("ok"):
            return result
        if result.get("reason") == "missing_parameters" and missing_match is None:
            missing_match = result
    return missing_match
