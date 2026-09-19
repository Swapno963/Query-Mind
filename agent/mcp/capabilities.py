from __future__ import annotations

import logging
import re
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
    has_deictic_reference,
)

logger = logging.getLogger("querymind.mcp")

RESOURCE_ALIASES = {
    "menu": "item",
    "menuitem": "item",
    "menu_item": "item",
    "categories": "category",
    "menucategory": "category",
    "menu_category": "category",
}

# Longer stems first. Tool names are the source of truth; descriptions often
# mention "restaurant" as tenancy and must not steal the resource.
RESOURCE_STEMS = (
    ("categor", "category"),
    ("menu_item", "item"),
    ("invoice", "invoice"),
    ("customer", "customer"),
    ("product", "product"),
    ("order", "order"),
    ("table", "table"),
    ("restaurant", "restaurant"),
    ("item", "item"),
    ("menu", "menu"),
    ("user", "user"),
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
IDENTITY_TOOL_PREFIXES = ("get_", "fetch_", "update_", "delete_", "mark_", "remove_")
LIST_TOOL_PREFIXES = ("list_", "search_", "find_")
PAID_VALUES = {"paid", "unpaid"}
HARD_REJECT_REASONS = {
    "operation_mismatch",
    "resource_mismatch",
    "aggregation_unsupported",
    "join_unsupported",
    "group_unsupported",
    "filter_unsupported",
}
_SINGLE_RECORD_RE = re.compile(
    r"\bthe\s+(order|item|category|table|customer|product|invoice)\b",
    re.I,
)
_PLURAL_RECORD_RE = re.compile(
    r"\b(orders|items|categories|tables|customers|products|invoices)\b",
    re.I,
)


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


def _normalize_resource(value: str | None) -> str:
    raw = _singular(str(value or "").strip().lower().replace(" ", "_").replace("-", "_"))
    return RESOURCE_ALIASES.get(raw, raw)


def _resource_from_text(text: str) -> str | None:
    normalized = f"_{(text or '').lower().replace('-', '_').replace(' ', '_')}_"
    for stem, resource in RESOURCE_STEMS:
        if f"_{stem}" in normalized:
            return resource
    return None


def infer_resource(name: str, description: str = "") -> str | None:
    from_name = _resource_from_text(name)
    if from_name:
        return from_name
    parts = [part for part in (name or "").lower().replace("-", "_").split("_") if part]
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
        "authenticated",
    }
    leftovers = [part for part in parts if part not in skip]
    if leftovers:
        return _singular(leftovers[-1])
    return _resource_from_text(description)


def resources_compatible(intent_resource: str | None, tool_resource: str | None, tool_name: str) -> bool:
    intent_n = _normalize_resource(intent_resource)
    if not intent_n:
        return False
    tool_n = _normalize_resource(tool_resource)
    if intent_n == tool_n:
        return True
    name = (tool_name or "").lower().replace("-", "_")
    return intent_n in name


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


def _property_alias(key: str) -> str:
    return PARAM_ALIASES.get(str(key).lower().replace("-", "_"), str(key).lower().replace("-", "_"))


def _is_ignored_param(key: str) -> bool:
    alias = _property_alias(key)
    return alias in IGNORED_PARAMS or str(key).lower().replace("-", "_") in IGNORED_PARAMS


def _is_identity_alias(alias: str) -> bool:
    return alias == "id" or alias.endswith("_id")


def bind_arguments(intent: dict[str, Any], tool: dict[str, Any]) -> dict[str, Any]:
    properties = schema_properties(tool)
    params = dict(intent.get("parameters") or {})
    bound: dict[str, Any] = {}
    for prop in properties:
        key = str(prop)
        lowered = key.lower().replace("-", "_")
        if _is_ignored_param(key):
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


def _schema_dict(tool: dict[str, Any]) -> dict[str, Any]:
    schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    return schema if isinstance(schema, dict) else {}


def _required_fields(tool: dict[str, Any]) -> list[str]:
    required = _schema_dict(tool).get("required") or []
    if not isinstance(required, list):
        return []
    return [str(item) for item in required if not _is_ignored_param(str(item))]


def _tool_name(tool: dict[str, Any]) -> str:
    return str(tool.get("name") or "").lower().replace("-", "_")


def effective_required_groups(tool: dict[str, Any]) -> list[list[str]]:
    advertised = _required_fields(tool)
    if advertised:
        return [[field] for field in advertised]
    name = _tool_name(tool)
    if not name.startswith(IDENTITY_TOOL_PREFIXES):
        return []
    id_fields: list[str] = []
    name_fields: list[str] = []
    for prop in schema_properties(tool):
        key = str(prop)
        if _is_ignored_param(key):
            continue
        alias = _property_alias(key)
        if _is_identity_alias(alias):
            id_fields.append(key)
        elif alias == "name":
            name_fields.append(key)
    if id_fields and name_fields:
        return [id_fields + name_fields]
    if id_fields:
        return [id_fields]
    if name_fields:
        return [name_fields]
    return []


def _missing_required(tool: dict[str, Any], bound: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for group in effective_required_groups(tool):
        if any(bound.get(field) not in (None, "") for field in group):
            continue
        missing.extend(group)
    return list(dict.fromkeys(missing))


def _coerce_schema_value(spec: dict[str, Any], value: Any) -> tuple[Any, bool]:
    expected = spec.get("type")
    enum = spec.get("enum")
    coerced = value
    if expected == "integer":
        if isinstance(value, bool):
            return value, False
        if isinstance(value, int):
            coerced = value
        elif isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
            coerced = int(value.strip())
        else:
            return value, False
    elif expected == "number":
        if isinstance(value, bool):
            return value, False
        if isinstance(value, (int, float)):
            coerced = float(value)
        elif isinstance(value, str):
            try:
                coerced = float(value.strip())
            except ValueError:
                return value, False
        else:
            return value, False
    elif expected == "boolean":
        if isinstance(value, bool):
            coerced = value
        elif str(value).strip().lower() in {"true", "false"}:
            coerced = str(value).strip().lower() == "true"
        else:
            return value, False
    elif expected == "string" and value is not None and not isinstance(value, str):
        coerced = str(value)
    if enum is not None and coerced not in enum:
        return coerced, False
    return coerced, True


def _validate_bound_arguments(
    tool: dict[str, Any], bound: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    properties = schema_properties(tool)
    cleaned: dict[str, Any] = {}
    invalid: list[str] = []
    for key, value in bound.items():
        spec = properties.get(key)
        if not isinstance(spec, dict):
            cleaned[key] = value
            continue
        coerced, ok = _coerce_schema_value(spec, value)
        if not ok:
            invalid.append(key)
            continue
        cleaned[key] = coerced
    return cleaned, invalid


def _intent_identity_aliases(intent: dict[str, Any]) -> dict[str, Any]:
    identities: dict[str, Any] = {}
    for key, value in dict(intent.get("parameters") or {}).items():
        if value in (None, ""):
            continue
        alias = _property_alias(str(key))
        if alias in IGNORED_PARAMS or not _is_identity_alias(alias):
            continue
        identities[alias] = value
    return identities


def _dropped_identifiers(
    intent: dict[str, Any], tool: dict[str, Any], bound: dict[str, Any]
) -> list[str]:
    accepted = schema_property_names(tool)
    bound_aliases = {_property_alias(str(key)) for key in bound}
    dropped: list[str] = []
    for alias in _intent_identity_aliases(intent):
        if alias in bound_aliases:
            continue
        if alias in accepted:
            continue
        dropped.append(alias)
    return dropped


def _is_paid_intent(intent: dict[str, Any], question: str = "") -> bool:
    params = dict(intent.get("parameters") or {})
    status = str(params.get("status") or params.get("payment_status") or "").lower()
    if status in PAID_VALUES:
        return True
    return bool(re.search(r"\b(paid|unpaid|payment)\b", question or "", re.I))


def wants_single_record(intent: dict[str, Any], question: str = "") -> bool:
    action = str(intent.get("action") or "")
    if action == "get":
        return True
    if _intent_identity_aliases(intent):
        return True
    q = question or ""
    if has_deictic_reference(q):
        return True
    if _SINGLE_RECORD_RE.search(q) and not _PLURAL_RECORD_RE.search(q):
        return True
    return False


def _score_match(
    intent: dict[str, Any],
    tool: dict[str, Any],
    result: dict[str, Any],
    question: str = "",
) -> int:
    reason = str(result.get("reason") or "")
    if reason in HARD_REJECT_REASONS:
        return -1000
    name = _tool_name(tool)
    score = 0
    dropped = result.get("dropped_identifiers") or []
    if dropped:
        score -= 25
    if result.get("ok"):
        score += 10
    elif reason in {"missing_parameters", "invalid_parameters"}:
        score += 7
    elif reason == "identifier_dropped":
        score -= 20
    if wants_single_record(intent, question):
        if name.startswith(("get_", "fetch_")):
            score += 8
        if name.startswith(LIST_TOOL_PREFIXES):
            score -= 8
    else:
        if name.startswith(LIST_TOOL_PREFIXES):
            score += 5
        if name.startswith(("get_", "fetch_")):
            score -= 3
    if _is_paid_intent(intent, question):
        if "paid" in name:
            score += 10
        if name == "update_order_status":
            score -= 6
    bound = result.get("arguments") or {}
    bound_aliases = {_property_alias(str(key)) for key in bound}
    for alias in _intent_identity_aliases(intent):
        if alias in bound_aliases:
            score += 6
    return score


def _is_specific_tool(name: str) -> bool:
    return name.startswith(IDENTITY_TOOL_PREFIXES)


def tool_satisfies(intent: dict[str, Any], tool: dict[str, Any]) -> dict[str, Any]:
    capability = capability_from_tool(tool)
    operation = str(intent.get("operation") or "").upper()
    if capability["operation"] != operation:
        return {"ok": False, "reason": "operation_mismatch", "tool": tool.get("name")}
    intent_resource = _singular(str(intent.get("resource") or ""))
    tool_resource = _singular(str(capability.get("resource") or ""))
    properties = schema_property_names(tool)
    tool_name = str(tool.get("name") or "")
    if not resources_compatible(intent_resource, tool_resource, tool_name):
        if "resource" not in properties:
            return {"ok": False, "reason": "resource_mismatch", "tool": tool_name}
    features = {str(item).lower() for item in (intent.get("query_features") or [])}
    if "aggregation" in features and not capability["constraints"]["aggregation"]:
        if operation != READ:
            return {"ok": False, "reason": "aggregation_unsupported", "tool": tool_name}
        logger.debug(
            "allowing READ tool %s for count/aggregation question",
            tool_name,
        )
    if "join" in features and not capability["constraints"]["join"]:
        return {"ok": False, "reason": "join_unsupported", "tool": tool.get("name")}
    if "group" in features and not capability["constraints"]["aggregation"]:
        return {"ok": False, "reason": "group_unsupported", "tool": tool.get("name")}
    if "unbounded_filter" in features and not (
        properties & {"filter", "query", "q", "search", "where"}
    ):
        return {"ok": False, "reason": "filter_unsupported", "tool": tool.get("name")}
    bound = bind_arguments(intent, tool)
    bound, invalid = _validate_bound_arguments(tool, bound)
    missing = _missing_required(tool, bound)
    dropped = _dropped_identifiers(intent, tool, bound)
    result = {
        "tool": tool.get("name"),
        "arguments": bound,
        "capability": redact(capability),
        "missing": missing,
        "invalid": invalid,
        "dropped_identifiers": dropped,
    }
    if invalid:
        result["missing"] = list(dict.fromkeys([*missing, *invalid]))
        return {**result, "ok": False, "reason": "invalid_parameters"}
    if missing:
        return {**result, "ok": False, "reason": "missing_parameters"}
    if dropped:
        return {**result, "ok": False, "reason": "identifier_dropped"}
    return {**result, "ok": True, "reason": "schema_match"}


def first_matching_tool(
    intent: dict[str, Any],
    tools: list[dict[str, Any]],
    question: str = "",
) -> dict[str, Any] | None:
    scored: list[dict[str, Any]] = []
    rejections: list[str] = []
    for tool in tools or []:
        result = tool_satisfies(intent, tool)
        result["score"] = _score_match(intent, tool, result, question)
        reason = result.get("reason") or "rejected"
        rejections.append(f"{tool.get('name')}:{reason}:{result['score']}")
        if result["score"] <= -50:
            continue
        scored.append(result)
    if not scored:
        logger.info(
            "mcp no match op=%s resource=%s tried=%s",
            intent.get("operation"),
            intent.get("resource"),
            ", ".join(rejections) or "(no tools)",
        )
        return None
    scored.sort(key=lambda item: int(item.get("score") or 0), reverse=True)
    best = scored[0]
    if wants_single_record(intent, question):
        specific = [
            item
            for item in scored
            if _is_specific_tool(str(item.get("tool") or "").lower().replace("-", "_"))
        ]
        if specific:
            best = max(specific, key=lambda item: int(item.get("score") or 0))
    if best.get("ok"):
        logger.info(
            "mcp match tool=%s reason=%s score=%s arguments=%s",
            best.get("tool"),
            best.get("reason"),
            best.get("score"),
            redact(best.get("arguments") or {}),
        )
        return best
    if best.get("reason") in {"missing_parameters", "invalid_parameters"}:
        logger.info(
            "mcp clarify tool=%s reason=%s missing=%s tried=%s",
            best.get("tool"),
            best.get("reason"),
            best.get("missing") or [],
            ", ".join(rejections),
        )
        return best
    logger.info(
        "mcp no match op=%s resource=%s tried=%s",
        intent.get("operation"),
        intent.get("resource"),
        ", ".join(rejections) or "(no tools)",
    )
    return None
