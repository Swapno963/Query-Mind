from __future__ import annotations

import json
from typing import Any

from agent.llm import ask_state
from agent.nodes.sql_generator import _clean_sql
from connections.services.engines import sql_language_name, sqlglot_dialect

from ..state import QueryMindState


def sql_repair(state: QueryMindState) -> dict[str, Any]:
    question = state.question
    sql = (state.sql or "").strip()
    database_error = (state.database_error or state.validation_error or "").strip()
    schema = state.schema if isinstance(state.schema, str) else state.schema_text
    error_analysis = state.error_analysis or {}

    if not question:
        return {
            "error_analysis": {**error_analysis, "repair_error": "No user question available."},
            "current_node": "sql_repair",
            "status": "failed",
        }
    if not sql:
        return {
            "error_analysis": {**error_analysis, "repair_error": "No SQL query available to repair."},
            "current_node": "sql_repair",
            "status": "failed",
        }
    if not database_error:
        return {
            "error_analysis": {**error_analysis, "repair_error": "No database error available."},
            "current_node": "sql_repair",
            "status": "failed",
        }

    prompt = _build_repair_prompt(
        question=question,
        schema=schema or "",
        sql=sql,
        database_error=database_error,
        error_analysis=error_analysis,
        intent=state.intent or {},
        critic=state.critic_result or {},
        explain=state.explain_result or {},
        sql_language=sql_language_name(state.engine),
    )
    system = f"You emit a single {sql_language_name(state.engine)} SELECT statement. No markdown."
    try:
        repaired_sql = _clean_sql(
            ask_state(
                state,
                prompt,
                temperature=0.2,
                system=system,
            )
        )
    except Exception as exc:
        return {
            "error_analysis": {**error_analysis, "repair_error": str(exc)},
            "current_node": "sql_repair",
            "status": "failed",
        }

    extras = []
    for _ in range(2):
        extra = _clean_sql(
            ask_state(
                state,
                prompt,
                temperature=0.35,
                system=system,
            )
        )
        if extra:
            extras.append(extra)
    from connections.services.sql_critic import rank_sql_candidates

    ranked = rank_sql_candidates(
        [repaired_sql, *extras],
        intent=state.intent,
        relationships=state.relationships,
        allowed_tables=state.allowed_tables,
        dialect=sqlglot_dialect(state.engine),
    )
    repaired_sql = ranked or repaired_sql
    if not repaired_sql:
        return {
            "error_analysis": {**error_analysis, "repair_error": "LLM returned an empty SQL query."},
            "current_node": "sql_repair",
            "status": "failed",
        }

    return {
        "sql": repaired_sql,
        "sql_candidates": [repaired_sql, *extras],
        "sql_attempts": state.sql_attempts + 1,
        "retry_count": state.retry_count + 1,
        "database_error": None,
        "validation_result": {},
        "execution_result": {},
        "explain_result": {},
        "critic_result": {},
        "error_analysis": {**error_analysis, "repair_error": None, "repaired": True},
        "current_node": "sql_repair",
        "status": "running",
    }


def _build_repair_prompt(
    *,
    question: str,
    schema: str,
    sql: str,
    database_error: str,
    error_analysis: dict[str, Any],
    intent: dict[str, Any],
    critic: dict[str, Any],
    explain: dict[str, Any],
    sql_language: str = "PostgreSQL",
) -> str:
    return f"""
You are a SQL repair engine.

Repair the SQL so it implements the intent without changing grain.
If the error is fan_out_on_sum, aggregate the parent table only or use EXISTS.

USER QUESTION:
{question}

STRUCTURED INTENT:
{json.dumps(intent, indent=2, default=str)}

DATABASE SCHEMA:
{schema}

ORIGINAL SQL:
{sql}

DATABASE / VALIDATION ERROR:
{database_error}

CRITIC:
{json.dumps(critic, indent=2, default=str)}

EXPLAIN:
{json.dumps(explain, indent=2, default=str)}

ERROR ANALYSIS:
{json.dumps(error_analysis, indent=2, default=str)}

REPAIR RULES:
1. Return ONLY the corrected {sql_language} SQL query.
2. Do NOT return Markdown or ```sql.
3. Only generate a single SELECT.
4. Use only tables and columns in the schema.
5. Preserve the user's original intent and grain.

Return only the repaired SQL.
""".strip()
