from __future__ import annotations

import json
import re
from typing import Any

from chat.api.chat_service import ChatService


READ = "READ"
CREATE = "CREATE"
UPDATE = "UPDATE"
DELETE = "DELETE"
ACTION = "ACTION"

OPERATIONS = {READ, CREATE, UPDATE, DELETE, ACTION}
WRITE_OPERATIONS = {CREATE, UPDATE, DELETE, ACTION}

PARAM_ALIASES = {
    "id": "id",
    "order_id": "order_id",
    "orderid": "order_id",
    "customer_id": "customer_id",
    "product_id": "product_id",
    "status": "status",
    "limit": "limit",
}

_DELETE_RE = re.compile(r"\b(delete|remove|erase)\b", re.I)
_UPDATE_RE = re.compile(r"\b(update|change|edit|rename|modify|set|mark)\b", re.I)
_CREATE_RE = re.compile(r"\b(create|insert|register|add)\b", re.I)
_ACTION_RE = re.compile(r"\b(cancel|refund|ship|fulfill|approve|reject)\b", re.I)
_READ_RE = re.compile(
    r"\b(show|list|get|find|display|fetch|count|how many|what|who|which|tell me)\b",
    re.I,
)
_AMBIGUOUS_RE = re.compile(r"\b(handle|deal with|do something|process this)\b", re.I)
_ORDER_ID_RE = re.compile(r"\border\s+#?(\d+)\b", re.I)
_STATUS_RE = re.compile(r"\b(?:as|to|status)\s+([a-z][a-z_]+)\b", re.I)
_LIMIT_RE = re.compile(r"\b(?:top|first|limit)\s+(\d+)\b", re.I)
_RESOURCE_RE = re.compile(
    r"\b(orders?|customers?|products?|users?|items?|invoices?)\b",
    re.I,
)


def empty_operation_intent() -> dict[str, Any]:
    return {
        "valid": False,
        "operation": None,
        "resource": None,
        "action": None,
        "parameters": {},
        "query_features": [],
        "reason": "",
    }


def validate_operation_intent(intent: dict[str, Any] | None) -> dict[str, Any]:
    bound = dict(intent or empty_operation_intent())
    operation = str(bound.get("operation") or "").upper()
    if operation not in OPERATIONS:
        bound["valid"] = False
        bound["reason"] = bound.get("reason") or "needs_clarification"
        return bound
    bound["operation"] = operation
    params = bound.get("parameters") if isinstance(bound.get("parameters"), dict) else {}
    clean: dict[str, Any] = {}
    for key, value in params.items():
        alias = PARAM_ALIASES.get(str(key).lower().replace("-", "_"), str(key).lower())
        if value not in (None, ""):
            clean[alias] = value
    bound["parameters"] = clean
    features = []
    for item in bound.get("query_features") or []:
        name = str(item).lower()
        if name in {"aggregation", "join", "group", "unbounded_filter"} and name not in features:
            features.append(name)
    bound["query_features"] = features
    resource = str(bound.get("resource") or "").strip().lower()
    bound["resource"] = resource or None
    bound["action"] = str(bound.get("action") or "").strip().lower() or None
    bound["valid"] = True
    bound["reason"] = ""
    return bound


def detect_query_features(question: str) -> list[str]:
    q = (question or "").lower()
    features: list[str] = []
    if any(
        token in q
        for token in (
            "revenue",
            "sum",
            "total",
            "highest",
            "lowest",
            "average",
            "avg",
            "how many",
            "count",
            "top ",
        )
    ):
        features.append("aggregation")
    if any(token in q for token in ("more than", "less than", "from ", "who spent", "who placed")):
        if "unbounded_filter" not in features:
            features.append("unbounded_filter")
    if any(token in q for token in (" join ", " who placed", " lifetime")):
        features.append("join")
    if " by " in q or " per " in q or "grouped" in q:
        features.append("group")
    return features


def extract_parameters(question: str) -> dict[str, Any]:
    params: dict[str, Any] = {}
    match = _ORDER_ID_RE.search(question or "")
    if match:
        params["order_id"] = match.group(1)
    status = _STATUS_RE.search(question or "")
    if status:
        value = status.group(1).lower()
        if value not in {"status"}:
            params["status"] = value
    limit = _LIMIT_RE.search(question or "")
    if limit:
        params["limit"] = int(limit.group(1))
    return params


def extract_resource(question: str) -> str | None:
    match = _RESOURCE_RE.search(question or "")
    if not match:
        return None
    return _singular(match.group(1).lower())


def _singular(name: str) -> str:
    raw = (name or "").strip().lower()
    if raw.endswith("ies") and len(raw) > 3:
        return raw[:-3] + "y"
    if raw.endswith("ses"):
        return raw[:-2]
    if raw.endswith("s") and not raw.endswith("ss"):
        return raw[:-1]
    return raw


def mutation_verb_operation(question: str) -> str | None:
    q = question or ""
    if _DELETE_RE.search(q):
        return DELETE
    if _ACTION_RE.search(q):
        return ACTION
    if _UPDATE_RE.search(q):
        return UPDATE
    if _CREATE_RE.search(q):
        return CREATE
    return None


def rule_based_operation(question: str) -> dict[str, Any]:
    q = (question or "").strip()
    intent = empty_operation_intent()
    if not q:
        intent["reason"] = "needs_clarification"
        return intent
    if _AMBIGUOUS_RE.search(q) and not mutation_verb_operation(q) and not _READ_RE.search(q):
        intent["reason"] = "needs_clarification"
        return intent

    operation = mutation_verb_operation(q)
    if operation is None:
        if _READ_RE.search(q) or q.endswith("?"):
            operation = READ
        else:
            intent["reason"] = "needs_clarification"
            return intent

    action = "search"
    if operation == READ and extract_parameters(q).get("order_id"):
        action = "get"
    elif operation == UPDATE:
        action = "change_status" if "status" in extract_parameters(q) or "mark" in q.lower() else "update"
    elif operation == DELETE:
        action = "delete"
    elif operation == CREATE:
        action = "create"
    elif operation == ACTION:
        action = "action"

    intent.update(
        {
            "operation": operation,
            "resource": extract_resource(q),
            "action": action,
            "parameters": extract_parameters(q),
            "query_features": detect_query_features(q),
        }
    )
    return validate_operation_intent(intent)


def llm_operation(question: str, conversation_context: str = "") -> dict[str, Any]:
    prompt = f"""
Convert the user request into JSON operation intent. Do not execute anything.

Allowed operation values: READ, CREATE, UPDATE, DELETE, ACTION.
If the request is ambiguous, set valid to false and reason to needs_clarification.

Return JSON only:
{{
  "valid": true,
  "operation": "READ",
  "resource": "orders",
  "action": "get",
  "parameters": {{}},
  "query_features": [],
  "reason": ""
}}

query_features may include aggregation, join, group, unbounded_filter.

CONVERSATION:
{conversation_context or "None"}

REQUEST:
{question}
""".strip()
    raw = ChatService.ask_on_premise_ai(
        prompt,
        temperature=0.0,
        system="You emit JSON only. You do not execute operations.",
    )
    start = raw.find("{")
    end = raw.rfind("}")
    parsed = json.loads(raw[start : end + 1]) if start >= 0 and end > start else {}
    if not isinstance(parsed, dict):
        return empty_operation_intent() | {"reason": "needs_clarification"}
    if parsed.get("valid") is False:
        parsed["reason"] = parsed.get("reason") or "needs_clarification"
        parsed["valid"] = False
        return parsed
    return validate_operation_intent(parsed)


def extract_operation(
    question: str,
    conversation_context: str = "",
    *,
    use_llm: bool = True,
) -> dict[str, Any]:
    forced = mutation_verb_operation(question)
    ruled = rule_based_operation(question)
    if forced:
        ruled["operation"] = forced
        return validate_operation_intent(ruled)
    if ruled.get("valid"):
        return ruled
    if ruled.get("reason") == "needs_clarification" and _AMBIGUOUS_RE.search(question or ""):
        return ruled
    if not use_llm:
        return ruled
    try:
        llm = llm_operation(question, conversation_context)
    except Exception:
        return ruled
    if forced:
        llm["operation"] = forced
        return validate_operation_intent(llm)
    return llm
