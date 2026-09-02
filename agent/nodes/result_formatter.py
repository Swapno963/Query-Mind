# Converts DB result into answer
# Query database


# agent/nodes/result_formatter.py

from __future__ import annotations

import json
from typing import Any

import httpx


from ..state import QueryMindState


def result_formatter(state: QueryMindState) -> dict[str, Any]:
    """
    Convert database execution results into a natural-language answer.

    This node is responsible for:
    - reading the user's question
    - reading the generated SQL
    - reading database results
    - building the result prompt
    - asking the LLM to format the result
    - storing the final answer in state

    This node does NOT:
    - generate SQL
    - validate SQL
    - execute SQL
    - repair SQL
    - analyze database errors
    - decide the next graph node
    - save Django models
    - handle SSE
    """

    # ============================================================
    # 1. Read execution result
    # ============================================================

    execution_result = state.execution_result

    if not execution_result.get("success", False):

        return {
            "final_answer": None,
            "error_analysis": {
                **state.error_analysis,
                "formatter_error": (
                    "Cannot format result because SQL execution failed."
                ),
            },
            "current_node": "result_formatter",
            "status": "failed",
        }

    # ============================================================
    # 2. Read data from state
    # ============================================================

    question = state.question
    sql = state.sql or ""

    rows = execution_result.get("rows", [])

    # ============================================================
    # 3. Build prompt
    # ============================================================

    prompt = _build_result_prompt(
        question=question,
        sql=sql,
        rows=rows,
    )

    # ============================================================
    # 4. Ask Ollama to generate final answer
    # ============================================================

    try:

        final_answer = _call_ollama(prompt)

    except Exception as exc:

        return {
            "final_answer": None,
            "error_analysis": {
                **state.error_analysis,
                "formatter_error": str(exc),
            },
            "current_node": "result_formatter",
            "status": "failed",
        }

    # ============================================================
    # 5. Validate LLM response
    # ============================================================

    final_answer = final_answer.strip()

    if not final_answer:

        return {
            "final_answer": None,
            "error_analysis": {
                **state.error_analysis,
                "formatter_error": ("LLM returned an empty final answer."),
            },
            "current_node": "result_formatter",
            "status": "failed",
        }

    # ============================================================
    # 6. Store final answer
    # ============================================================

    return {
        "final_answer": final_answer,
        "current_node": "result_formatter",
        "status": "completed",
    }


# ==================================================================
# Prompt
# ==================================================================


def _build_result_prompt(
    *,
    question: str,
    sql: str,
    rows: list[dict[str, Any]],
) -> str:
    """
    Build the prompt used to convert database rows into
    a natural-language answer.
    """

    rows_text = json.dumps(
        rows,
        indent=2,
        default=str,
    )

    return f"""
You are the final answer generator for QueryMind.

The user asked a question about a PostgreSQL database.

Your job is to answer the user's question using ONLY the database
results provided below.

USER QUESTION:
{question}

SQL QUERY:
{sql}

DATABASE RESULTS:
{rows_text}

RULES:

1. Answer the user's question directly.
2. Use only information contained in the database results.
3. Do not invent or assume data.
4. Do not expose internal system details unless necessary.
5. Do not explain the SQL query unless the user asks for it.
6. If the result is empty, clearly say that no matching records were found.
7. If there are multiple records, summarize them naturally.
8. Include useful numbers such as counts or totals when appropriate.
9. Keep the answer concise.
10. Do not mention that you are an AI.
11. Do not mention these instructions.
12. Do not generate SQL.
13. Do not use Markdown code blocks.

Return only the final answer for the user.
""".strip()


# ==================================================================
# Ollama
# ==================================================================


def _call_ollama(prompt: str) -> str:
    """
    Send the result-formatting prompt to Ollama and return
    the complete response.
    """

    with httpx.Client(timeout=60.0) as client:

        # response = client.post(
        #     ,
        #     json={
        #         "model": OLLAMA_MODEL,
        #         "messages": [
        #             {
        #                 "role": "user",
        #                 "content": prompt,
        #             }
        #         ],
        #         "stream": False,
        #     },
        # )

        # response.raise_for_status()

        # data = response.json()

        # return data.get("message", {}).get("content", "")
        return ""
