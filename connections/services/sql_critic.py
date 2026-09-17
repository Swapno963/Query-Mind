from __future__ import annotations

from typing import Any

import sqlglot
from sqlglot import exp


def critique_sql(
    sql: str,
    *,
    intent: dict[str, Any] | None = None,
    relationships: list[dict[str, str]] | None = None,
    allowed_tables: list[str] | None = None,
    dialect: str = "postgres",
) -> dict[str, Any]:
    issues: list[str] = []
    ir = intent or {}
    try:
        statements = sqlglot.parse(sql or "", dialect=dialect)
    except Exception as exc:
        return {"ok": False, "issues": [f"parse_error: {exc}"], "confidence": 0.0}

    if len(statements) != 1 or statements[0] is None:
        return {"ok": False, "issues": ["not_single_statement"], "confidence": 0.0}

    expression = statements[0]
    if not isinstance(expression, exp.Select):
        return {"ok": False, "issues": ["not_select"], "confidence": 0.0}

    outer_tables = _outer_tables(expression)
    if _has_fan_out_aggregate(expression, relationships or []):
        issues.append("fan_out_on_sum")

    group_issue = _group_by_issue(expression)
    if group_issue:
        issues.append(group_issue)

    intent_tables = {str(name).lower() for name in (ir.get("tables") or []) if name}
    entity = str(ir.get("entity") or "").lower()
    if entity:
        intent_tables.add(entity)
    if intent_tables and not (intent_tables & outer_tables) and not _uses_exists_for(expression, intent_tables):
        missing = ", ".join(sorted(intent_tables - outer_tables))
        issues.append(f"missing_intent_tables:{missing}")

    time_range = ir.get("time_range") or {}
    field = str(time_range.get("field") or "")
    if field and time_range.get("kind") and field.split(".")[-1].lower() not in _sql_lower(sql):
        issues.append("missing_time_filter")

    metric = ir.get("metric") or {}
    if isinstance(metric, dict) and str(metric.get("op") or "").lower() == "count":
        expr = str(metric.get("expr") or "").upper()
        if "COUNT(" in expr and "COUNT(*)" not in expr and "COUNT(*)" in (sql or "").upper():
            if "non-null" in str(ir.get("reason") or "").lower():
                issues.append("count_star_vs_column")

    if ir.get("output") == "scalar" and _has_limit(expression):
        issues.append("unexpected_limit")

    allowed = {str(name).lower() for name in (allowed_tables or []) if name}
    if allowed and outer_tables - allowed:
        issues.append(
            "hallucinated_tables:" + ",".join(sorted(outer_tables - allowed))
        )

    return {
        "ok": not issues,
        "issues": issues,
        "confidence": 0.9 if not issues else 0.3,
        "tables": sorted(outer_tables),
    }


def rank_sql_candidates(
    candidates: list[str],
    *,
    intent: dict[str, Any] | None = None,
    relationships: list[dict[str, str]] | None = None,
    allowed_tables: list[str] | None = None,
    dialect: str = "postgres",
) -> str | None:
    scored: list[tuple[int, str]] = []
    for sql in candidates:
        cleaned = (sql or "").strip()
        if not cleaned:
            continue
        result = critique_sql(
            cleaned,
            intent=intent,
            relationships=relationships,
            allowed_tables=allowed_tables,
            dialect=dialect,
        )
        score = 0
        if result["ok"]:
            score += 100
        score -= 20 * len(result["issues"])
        if "fan_out_on_sum" in result["issues"]:
            score -= 50
        upper = cleaned.upper()
        if "EXISTS" in upper or " IN (" in upper:
            score += 5
        scored.append((score, cleaned))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def _sql_lower(sql: str) -> str:
    return (sql or "").lower()


def _outer_tables(expression: exp.Expression) -> set[str]:
    names: set[str] = set()
    for table in expression.find_all(exp.Table):
        if _under_subquery(table):
            continue
        if table.name:
            names.add(str(table.name).lower())
    return names


def _under_subquery(node: exp.Expression) -> bool:
    parent = node.parent
    while parent is not None:
        if isinstance(parent, (exp.Subquery, exp.Exists, exp.Unnest)):
            return True
        parent = parent.parent
    return False


def _has_fan_out_aggregate(
    expression: exp.Expression,
    relationships: list[dict[str, str]],
) -> bool:
    many_from: dict[str, set[str]] = {}
    for rel in relationships:
        many = str(rel.get("source_table") or "").lower()
        one = str(rel.get("target_table") or "").lower()
        if many and one:
            many_from.setdefault(one, set()).add(many)

    outer = _outer_tables(expression)
    aggs = list(expression.find_all(exp.AggFunc))
    if not aggs:
        return False

    for agg in aggs:
        if _under_subquery(agg):
            continue
        for column in agg.find_all(exp.Column):
            table = str(column.table or "").lower()
            if not table:
                continue
            children = many_from.get(table) or set()
            if children & outer:
                return True
    return False


def _group_by_issue(expression: exp.Select) -> str | None:
    aggs = [node for node in expression.find_all(exp.AggFunc) if not _under_subquery(node)]
    if not aggs:
        return None
    grouped = {
        str(item).lower()
        for item in (expression.args.get("group") or exp.Group()).expressions
    }
    if expression.args.get("group") is None:
        selects = expression.args.get("expressions") or []
        non_agg = [
            item
            for item in selects
            if not item.find(exp.AggFunc) and not isinstance(item, exp.Star)
        ]
        if non_agg:
            return "missing_group_by"
        return None
    selects = expression.args.get("expressions") or []
    for item in selects:
        if item.find(exp.AggFunc):
            continue
        if isinstance(item, exp.Alias):
            inner = item.this
        else:
            inner = item
        if isinstance(inner, exp.Star):
            continue
        key = str(inner).lower()
        alias = str(item.alias or "").lower()
        if key not in grouped and alias not in grouped:
            return "group_by_mismatch"
    return None


def _has_limit(expression: exp.Select) -> bool:
    return expression.args.get("limit") is not None


def _uses_exists_for(expression: exp.Expression, tables: set[str]) -> bool:
    for node in expression.find_all(exp.Exists):
        inner_tables = {
            str(table.name).lower()
            for table in node.find_all(exp.Table)
            if table.name
        }
        if inner_tables & tables:
            return True
    return False
