from __future__ import annotations

import json
import re
from typing import Any

from agent.llm import ask_llm


OUTPUT_KINDS = {"scalar", "row_list", "grouped"}


def empty_intent() -> dict[str, Any]:
    return {
        "valid": False,
        "metric": None,
        "entity": None,
        "grain": "",
        "filters": [],
        "time_range": None,
        "output": "row_list",
        "joins": [],
        "tables": [],
        "reason": "",
    }


def _allowed_lookup(
    allowed_tables: list[str],
    allowed_columns: dict[str, list[str]],
) -> tuple[set[str], dict[str, set[str]]]:
    tables = {str(name).lower() for name in allowed_tables or [] if name}
    columns = {
        str(table).lower(): {str(col).lower() for col in (cols or [])}
        for table, cols in (allowed_columns or {}).items()
    }
    return tables, columns


def _split_column(ref: str) -> tuple[str, str]:
    raw = str(ref or "").strip()
    if "." in raw:
        table, column = raw.split(".", 1)
        return table.lower(), column.lower()
    return "", raw.lower()


def bind_intent_to_allow_list(
    intent: dict[str, Any],
    allowed_tables: list[str],
    allowed_columns: dict[str, list[str]],
) -> dict[str, Any]:
    bound = dict(intent or {})
    tables, columns = _allowed_lookup(allowed_tables, allowed_columns)
    if not tables or not columns:
        bound["valid"] = False
        bound["reason"] = "No allowed tables and columns."
        return bound

    entity = str(bound.get("entity") or "").lower()
    if entity and entity not in tables:
        bound["valid"] = False
        bound["reason"] = f"Entity {entity} is not allowed."
        return bound

    metric = bound.get("metric") or {}
    if isinstance(metric, dict) and metric.get("expr"):
        expr = str(metric.get("expr"))
        refs = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b", expr)
        for table, column in refs:
            allowed = columns.get(table.lower())
            if allowed is None or column.lower() not in allowed:
                bound["valid"] = False
                bound["reason"] = f"Metric column {table}.{column} is not allowed."
                return bound

    clean_filters = []
    for item in bound.get("filters") or []:
        if not isinstance(item, dict):
            continue
        table, column = _split_column(item.get("column") or "")
        if not table:
            table = entity
        allowed = columns.get(table)
        if not table or allowed is None or column not in allowed:
            bound["valid"] = False
            bound["reason"] = f"Filter {table}.{column} is not allowed."
            return bound
        clean = dict(item)
        clean["column"] = f"{table}.{column}"
        clean_filters.append(clean)
    bound["filters"] = clean_filters

    time_range = bound.get("time_range") or None
    if isinstance(time_range, dict) and time_range.get("field"):
        table, column = _split_column(time_range.get("field"))
        if not table:
            table = entity
        allowed = columns.get(table)
        if not table or allowed is None or column not in allowed:
            bound["valid"] = False
            bound["reason"] = f"Time field {table}.{column} is not allowed."
            return bound
        time_range = dict(time_range)
        time_range["field"] = f"{table}.{column}"
        bound["time_range"] = time_range

    listed = []
    for name in bound.get("tables") or []:
        if str(name).lower() in tables:
            listed.append(str(name).lower())
    if entity and entity not in listed:
        listed.insert(0, entity)
    bound["tables"] = listed
    if bound.get("output") not in OUTPUT_KINDS:
        bound["output"] = "row_list"
    bound["valid"] = True
    bound["reason"] = bound.get("reason") or ""
    return bound


def apply_glossary(intent: dict[str, Any], semantic_layer: dict[str, Any] | None) -> dict[str, Any]:
    layer = semantic_layer or {}
    aliases = layer.get("aliases") or {}
    metrics = layer.get("metrics") or {}
    updated = dict(intent or {})
    question_blob = json.dumps(updated).lower()

    metric_name = None
    if isinstance(updated.get("metric"), dict):
        metric_name = str(updated["metric"].get("name") or "").lower()
    if not metric_name and "revenue" in question_blob:
        metric_name = "revenue"
    if metric_name and metric_name in metrics:
        spec = metrics[metric_name]
        updated["metric"] = {
            "name": metric_name,
            "op": "sum",
            "expr": spec.get("expr"),
            "table": spec.get("table"),
        }
        updated["entity"] = spec.get("table") or updated.get("entity")
        updated["grain"] = spec.get("grain") or updated.get("grain")
        extra = list(updated.get("filters") or [])
        for item in spec.get("filters") or []:
            extra.append(item)
        updated["filters"] = extra
        updated["output"] = updated.get("output") or "scalar"

    resolved = []
    for item in updated.get("filters") or []:
        if not isinstance(item, dict):
            continue
        value = str(item.get("value") or item.get("value_ref") or "").strip()
        alias = aliases.get(value.lower())
        if alias:
            item = dict(item)
            item["column"] = alias.get("column") or item.get("column")
            item["op"] = item.get("op") or "eq"
            item["value"] = alias.get("value")
        resolved.append(item)
    updated["filters"] = resolved
    return updated


def is_hard_query(intent: dict[str, Any] | None) -> bool:
    ir = intent or {}
    joins = ir.get("joins") or []
    tables = ir.get("tables") or []
    metric = ir.get("metric") or {}
    has_metric = bool(isinstance(metric, dict) and metric.get("expr"))
    return bool(has_metric and (joins or len(tables) > 1))


def is_trivial_intent(intent: dict[str, Any] | None) -> bool:
    ir = intent or {}
    if not ir.get("valid"):
        return False
    tables = ir.get("tables") or []
    joins = ir.get("joins") or []
    metric = ir.get("metric") or {}
    has_metric = bool(isinstance(metric, dict) and metric.get("expr"))
    return len(tables) <= 1 and not joins and not has_metric


def rule_based_intent(
    question: str,
    allowed_tables: list[str],
    allowed_columns: dict[str, list[str]],
    semantic_layer: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    q = (question or "").strip().lower()
    if not q:
        return None
    tables, columns = _allowed_lookup(allowed_tables, allowed_columns)
    ir = empty_intent()

    if "revenue" in q or "how much" in q:
        ir.update(
            {
                "metric": {"name": "revenue", "op": "sum"},
                "output": "scalar",
            }
        )
    elif q.startswith("how many") or "count" in q:
        ir.update(
            {
                "metric": {"op": "count", "expr": "COUNT(*)"},
                "output": "scalar",
            }
        )

    for table in ("order_items", "orders", "products", "users"):
        if table in tables and table in q.replace(" ", "_"):
            ir["entity"] = table
            break
    if not ir.get("entity"):
        if "order item" in q or "line item" in q:
            ir["entity"] = "order_items" if "order_items" in tables else None
        elif "order" in q:
            ir["entity"] = "orders" if "orders" in tables else None
        elif "product" in q:
            ir["entity"] = "products" if "products" in tables else None
        elif "user" in q or "customer" in q:
            ir["entity"] = "users" if "users" in tables else None

    if ir.get("entity"):
        ir["tables"] = [ir["entity"]]
        ir["grain"] = "order" if ir["entity"] == "orders" else ir["entity"]

    if "last month" in q or "previous month" in q:
        entity = ir.get("entity") or "orders"
        field = "ordered_at" if entity == "orders" else "created_at"
        if field in columns.get(entity, set()):
            ir["time_range"] = {
                "field": f"{entity}.{field}",
                "kind": "previous_calendar_month",
            }

    if "paid" in q:
        ir["filters"] = [{"column": "orders.payment_status", "value_ref": "paid", "op": "eq"}]

    ir = apply_glossary(ir, semantic_layer)
    if not ir.get("entity") and not ir.get("metric"):
        return None
    return bind_intent_to_allow_list(ir, allowed_tables, allowed_columns)


def llm_intent(
    question: str,
    schema_text: str,
    conversation_context: str,
    allowed_tables: list[str],
    allowed_columns: dict[str, list[str]],
    semantic_layer: dict[str, Any] | None = None,
    backend: str = "local",
) -> dict[str, Any]:
    prompt = f"""
You convert a question into a JSON query intent. Use only this schema.

SCHEMA:
{schema_text}

CONVERSATION:
{conversation_context or "None"}

QUESTION:
{question}

Return ONLY JSON with keys:
valid, metric, entity, grain, filters, time_range, output, joins, tables, reason
metric is null or {{"op": "sum|count|avg", "expr": "table.column or COUNT(*)"}}
filters is a list of {{"column": "table.column", "op": "eq|gt|lt|in", "value": "..."}}
output is scalar, row_list, or grouped.
grain is the row grain (order, order_item, product, user).
Do not invent tables or columns.
""".strip()
    raw = ask_llm(
        prompt,
        backend=backend,
        temperature=0.1,
        system="You emit JSON only. Never emit SQL.",
    )
    parsed = _parse_json_object(raw) or empty_intent()
    parsed = apply_glossary(parsed, semantic_layer)
    return bind_intent_to_allow_list(parsed, allowed_tables, allowed_columns)


def _parse_json_object(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
