from __future__ import annotations

import json
from typing import Any

from chat.api.chat_service import ChatService
from connections.services.result_prompt import SQLResultPromptGenerator

from ..state import QueryMindState


def result_formatter(state: QueryMindState) -> dict[str, Any]:
    """
    Convert database execution results into a natural-language answer.
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
    kind = execution_result.get("kind") or ("zero_rows" if not rows else "success")

    if kind == "zero_rows" or not rows:
        return {
            "final_answer": (
                "No matching records in the tables you allowed."
            ),
            "answer_kind": "zero_rows",
            "current_node": "result_formatter",
            "status": "completed",
        }

    # ============================================================
    # 3. Generate result prompt
    # ============================================================

    prompt_generator = SQLResultPromptGenerator()

    answer_prompt = prompt_generator.generate(
        user_question=question,
        sql=sql,
        rows=rows,
    )

    # ============================================================
    # 4. Ask on-premise AI
    # ============================================================

    try:

        final_answer = ChatService.ask_on_premise_ai(answer_prompt)

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
    # 5. Validate AI response
    # ============================================================

    final_answer = (final_answer or "").strip()

    if not final_answer:

        return {
            "final_answer": None,
            "error_analysis": {
                **state.error_analysis,
                "formatter_error": "LLM returned an empty final answer.",
            },
            "current_node": "result_formatter",
            "status": "failed",
        }

    # ============================================================
    # 6. Store final answer
    # ============================================================

    return {
        "final_answer": final_answer,
        "answer_kind": "success",
        "current_node": "result_formatter",
        "status": "completed",
    }
