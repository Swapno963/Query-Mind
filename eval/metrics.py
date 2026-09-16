from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from connections.services.sql_critic import critique_sql
from connections.services.schema_discovery import extract_relationships_from_schema


CASES_DIR = Path(__file__).parent / "cases"


def load_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted(CASES_DIR.glob("*.json")):
        payload = json.loads(path.read_text())
        if isinstance(payload, list):
            cases.extend(payload)
        elif isinstance(payload, dict) and "cases" in payload:
            cases.extend(payload["cases"])
    return cases


def tables_from_sql(sql: str) -> set[str]:
    import sqlglot
    from sqlglot import exp

    try:
        parsed = sqlglot.parse_one(sql, dialect="postgres")
    except Exception:
        return set()
    return {
        str(table.name).lower()
        for table in parsed.find_all(exp.Table)
        if table.name
    }


def hallucinated_identifiers(sql: str, allowed_tables: list[str], allowed_columns: dict) -> list[str]:
    import sqlglot
    from sqlglot import exp

    issues = []
    allowed_t = {str(name).lower() for name in allowed_tables}
    allowed_c = {
        str(table).lower(): {str(col).lower() for col in cols or []}
        for table, cols in (allowed_columns or {}).items()
    }
    try:
        parsed = sqlglot.parse_one(sql, dialect="postgres")
    except Exception as exc:
        return [f"parse:{exc}"]
    for table in parsed.find_all(exp.Table):
        name = str(table.name or "").lower()
        if name and name not in allowed_t:
            issues.append(f"table:{name}")
    for column in parsed.find_all(exp.Column):
        table = str(column.table or "").lower()
        col = str(column.name or "").lower()
        if table and table in allowed_c and col not in allowed_c[table] and col != "*":
            issues.append(f"column:{table}.{col}")
    return issues


def score_prediction(case: dict[str, Any], *, sql: str | None, refused: bool, linked_tables: list[str] | None = None) -> dict[str, Any]:
    must_refuse = bool(case.get("must_refuse"))
    gold_tables = {str(name).lower() for name in case.get("gold_tables") or []}
    predicted = {str(name).lower() for name in (linked_tables or [])}
    if sql:
        predicted |= tables_from_sql(sql)

    if must_refuse:
        return {
            "id": case.get("id"),
            "refuse_ok": refused,
            "execution_ok": refused,
            "linking_f1": 1.0 if refused else 0.0,
            "hallucinations": [],
            "fan_out_ok": True,
        }

    if refused or not sql:
        return {
            "id": case.get("id"),
            "refuse_ok": False,
            "execution_ok": False,
            "linking_f1": _f1(predicted, gold_tables),
            "hallucinations": ["refused"],
            "fan_out_ok": False,
        }

    hallu = hallucinated_identifiers(
        sql,
        case.get("allowed_tables") or [],
        case.get("allowed_columns") or {},
    )
    critic = critique_sql(
        sql,
        intent={
            "tables": list(gold_tables),
            "entity": case.get("gold_grain"),
            "grain": case.get("gold_grain"),
            "metric": {"expr": "SUM(orders.total_amount)"} if case.get("category") == "fan_out" else None,
        },
        relationships=extract_relationships_from_schema(case.get("schema_text") or _demo_relationships()),
        allowed_tables=case.get("allowed_tables") or [],
    )
    fan_out_ok = "fan_out_on_sum" not in (critic.get("issues") or [])
    if case.get("must_not_join"):
        forbidden = {str(name).lower() for name in case["must_not_join"]}
        if tables_from_sql(sql) & forbidden and "SUM" in sql.upper() and "TOTAL_AMOUNT" in sql.upper():
            fan_out_ok = False

    return {
        "id": case.get("id"),
        "refuse_ok": True,
        "execution_ok": not hallu and fan_out_ok,
        "linking_f1": _f1(predicted, gold_tables),
        "hallucinations": hallu,
        "fan_out_ok": fan_out_ok,
        "critic_issues": critic.get("issues") or [],
    }


def _f1(predicted: set[str], gold: set[str]) -> float:
    if not gold and not predicted:
        return 1.0
    if not gold or not predicted:
        return 0.0
    overlap = len(predicted & gold)
    precision = overlap / len(predicted)
    recall = overlap / len(gold)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _demo_relationships() -> str:
    return """
RELATIONSHIPS:
- order_items.order_id → orders.id
- order_items.product_id → products.id
- orders.user_id → users.id
"""


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results) or 1
    return {
        "n": len(results),
        "execution_accuracy": round(sum(1 for item in results if item.get("execution_ok")) / total, 4),
        "fan_out_pass_rate": round(sum(1 for item in results if item.get("fan_out_ok")) / total, 4),
        "mean_linking_f1": round(sum(item.get("linking_f1") or 0 for item in results) / total, 4),
        "hallucination_rate": round(sum(1 for item in results if item.get("hallucinations")) / total, 4),
        "refuse_accuracy": round(sum(1 for item in results if item.get("refuse_ok")) / total, 4),
    }
