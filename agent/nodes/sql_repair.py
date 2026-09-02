# Produces corrected SQL
# Decide whether retry is allowed


# agent/nodes/sql_repair.py

from __future__ import annotations

import json
from typing import Any

import httpx

from connections.services.prompt import PromptGenerator
from chat.api.chat_service import ChatService

from ..state import QueryMindState


def sql_repair(state: QueryMindState) -> dict[str, Any]:
    """
    Repair SQL that failed during validation or database execution.

    This node is responsible for:
    - reading the failed SQL from state
    - reading the database error
    - reading the error analysis
    - reading the current schema
    - asking the LLM to generate corrected SQL
    - storing the repaired SQL in state
    - incrementing the SQL attempt counter

    This node does NOT:
    - validate SQL
    - execute SQL
    - decide the next graph node
    - modify the database
    - save Django models
    - stream SSE responses
    """

    # ============================================================
    # 1. Read state
    # ============================================================

    question = state.question
    sql = (state.sql or "").strip()
    database_error = (state.database_error or "").strip()

    schema = state.schema

    error_analysis = state.error_analysis

    # ============================================================
    # 2. Validate required state
    # ============================================================

    if not question:
        return {
            "error_analysis": {
                **error_analysis,
                "repair_error": "No user question available.",
            },
            "current_node": "sql_repair",
            "status": "failed",
        }

    if not sql:
        return {
            "error_analysis": {
                **error_analysis,
                "repair_error": "No SQL query available to repair.",
            },
            "current_node": "sql_repair",
            "status": "failed",
        }

    if not database_error:
        return {
            "error_analysis": {
                **error_analysis,
                "repair_error": "No database error available.",
            },
            "current_node": "sql_repair",
            "status": "failed",
        }

    # ============================================================
    # 3. Build repair prompt
    # ============================================================

    prompt = _build_repair_prompt(
        question=question,
        schema=schema,
        sql=sql,
        database_error=database_error,
        error_analysis=error_analysis,
    )

    # ============================================================
    # 4. Ask Ollama to repair SQL
    # ============================================================

    try:
        repaired_sql = ChatService.ask_ai(prompt)

    except Exception as exc:

        return {
            "error_analysis": {
                **error_analysis,
                "repair_error": str(exc),
            },
            "current_node": "sql_repair",
            "status": "failed",
        }

    # ============================================================
    # 5. Make sure the LLM actually returned SQL
    # ============================================================

    repaired_sql = _clean_sql(repaired_sql)

    if not repaired_sql:

        return {
            "error_analysis": {
                **error_analysis,
                "repair_error": "LLM returned an empty SQL query.",
            },
            "current_node": "sql_repair",
            "status": "failed",
        }

    # ============================================================
    # 6. Update state
    # ============================================================

    return {
        "sql": repaired_sql,
        "sql_attempts": state.sql_attempts + 1,
        # Clear the previous execution error because we are
        # going to validate/execute a new SQL attempt.
        "database_error": None,
        "validation_result": {},
        "execution_result": {},
        "error_analysis": {
            **error_analysis,
            "repair_error": None,
            "repaired": True,
        },
        "current_node": "sql_repair",
        "status": "running",
    }


# ==================================================================
# Prompt
# ==================================================================


def _build_repair_prompt(
    *,
    question: str,
    schema: dict[str, Any],
    sql: str,
    database_error: str,
    error_analysis: dict[str, Any],
) -> str:
    """
    Build the prompt used by the LLM to repair SQL.
    """

    schema_text = json.dumps(
        schema,
        indent=2,
        default=str,
    )

    error_analysis_text = json.dumps(
        error_analysis,
        indent=2,
        default=str,
    )

    return f"""
You are a  SQL repair engine.

Your task is to repair an SQL query that failed against a  database.

You MUST use the database schema provided below.

USER QUESTION:
{question}

DATABASE SCHEMA:
{schema_text}

ORIGINAL SQL:
{sql}

DATABASE ERROR:
{database_error}

ERROR ANALYSIS:
{error_analysis_text}

REPAIR RULES:

1. Return ONLY the corrected PostgreSQL SQL query.
2. Do NOT return Markdown.
3. Do NOT use ```sql.
4. Do NOT explain your answer.
5. Do NOT include comments.
6. Only generate a single SQL statement.
7. Only generate a SELECT query.
8. Do not INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE,
   GRANT, REVOKE, or any other write operation.
9. Use only tables and columns that exist in the provided schema.
10. Preserve the user's original intent.
11. Do not invent columns or tables.
12. If the error is caused by a wrong column, replace it with the
    correct column from the schema.
13. If the error is caused by a wrong table, use the correct table
    from the schema.
14. Do not change the meaning of the user's question.

Return only the repaired SQL.
""".strip()


# ==================================================================
# Ollama
# ==================================================================


# def _call_ollama(prompt: str) -> str:
#     """
#     Send the repair prompt to Ollama and return the complete response.
#     """

#     with httpx.Client(timeout=60.0) as client:

#         response = client.post(
#             OLLAMA_CHAT_ENDPOINT,
#             json={
#                 "model": OLLAMA_MODEL,
#                 "messages": [
#                     {
#                         "role": "user",
#                         "content": prompt,
#                     }
#                 ],
#                 "stream": False,
#             },
#         )

#         response.raise_for_status()

#         data = response.json()

#     return data.get("message", {}).get("content", "")


# ==================================================================
# SQL cleanup
# ==================================================================


def _clean_sql(sql: str) -> str:
    """
    Clean common formatting mistakes from the LLM response.

    This does NOT validate SQL.
    """

    sql = sql.strip()

    if not sql:
        return ""

    # Remove Markdown code fences if the model ignores the prompt.

    if sql.startswith("```sql"):
        sql = sql[6:]

    elif sql.startswith("```"):
        sql = sql[3:]

    if sql.endswith("```"):
        sql = sql[:-3]

    return sql.strip()
