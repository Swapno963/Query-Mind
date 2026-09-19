from __future__ import annotations

from typing import Any

from agent.intent import is_trivial_intent
from agent.llm import ask_state
from connections.services.result_prompt import SQLResultPromptGenerator

from ..state import QueryMindState


def result_formatter(state: QueryMindState) -> dict[str, Any]:
    """
    Convert database execution results into a natural-language answer.
    """

    execution_result = state.execution_result or {}

    if not execution_result.get("success", False):

        return {
            "final_answer": None,
            "error_analysis": {
                **(state.error_analysis or {}),
                "formatter_error": (
                    "Cannot format result because SQL execution failed."
                ),
            },
            "current_node": "result_formatter",
            "status": "failed",
        }

    question = state.question
    sql = state.sql or ""

    rows = execution_result.get("rows", []) or []
    kind = execution_result.get("kind") or ("zero_rows" if not rows else "success")

    if rows and isinstance(rows[0], dict) and rows[0].get("message") and rows[0].get("status"):
        return {
            "final_answer": str(rows[0].get("message")),
            "answer_kind": str(rows[0].get("status")),
            "current_node": "result_formatter",
            "status": "completed",
        }

    if kind == "zero_rows" or not rows:
        return {
            "final_answer": "No matching records in the tables you allowed.",
            "answer_kind": "zero_rows",
            "current_node": "result_formatter",
            "status": "completed",
        }

    if not _use_llm_narrative(state, rows):
        return {
            "final_answer": deterministic_result_answer(rows),
            "answer_kind": "success",
            "current_node": "result_formatter",
            "status": "completed",
        }

    prompt_generator = SQLResultPromptGenerator()
    answer_prompt = prompt_generator.generate(
        user_question=question,
        sql=sql,
        rows=rows,
    )

    try:
        final_answer = ask_state(state, answer_prompt)
    except Exception:
        return {
            "final_answer": deterministic_result_answer(rows),
            "answer_kind": "success",
            "current_node": "result_formatter",
            "status": "completed",
        }

    final_answer = (final_answer or "").strip()
    if not final_answer:
        final_answer = deterministic_result_answer(rows)

    return {
        "final_answer": final_answer,
        "answer_kind": "success",
        "current_node": "result_formatter",
        "status": "completed",
    }


def deterministic_result_answer(rows: list[dict[str, Any]] | None) -> str:
    rows = rows or []
    count = len(rows)
    if count == 0:
        return "No matching records in the tables you allowed."
    if count == 1 and len(rows[0]) <= 4:
        parts = [f"{key} is {rows[0][key]}" for key in rows[0]]
        return "From your allowed tables: " + ", ".join(parts) + "."
    noun = "row" if count == 1 else "rows"
    return f"Showing {count} matching {noun} from the tables you allowed."


def _use_llm_narrative(state: QueryMindState, rows: list[dict[str, Any]]) -> bool:
    if len(rows) >= 8:
        return False
    intent = state.intent or {}
    output = intent.get("output") or "row_list"
    if output == "row_list" or is_trivial_intent(intent):
        return False
    return output in {"scalar", "grouped"}
