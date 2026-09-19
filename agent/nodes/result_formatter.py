from __future__ import annotations

import re
from typing import Any

from agent.intent import is_trivial_intent
from agent.llm import ask_state
from agent.mcp.client import MCP_SOFT_STATUSES
from agent.operation import WRITE_OPERATIONS, wants_count_question
from connections.services.result_prompt import SQLResultPromptGenerator

from ..state import QueryMindState

_INJECTION_RE = re.compile(
    r"ignore (all )?(previous|prior) instructions|system prompt|you are now",
    re.I,
)

_HIDDEN_FIELDS = {
    "id",
    "pk",
    "restaurant_id",
    "restaurant",
    "menu_item_id",
    "category_id",
    "order_id",
    "user_id",
}
_TITLE_FIELDS = ("name", "title", "table", "label")
_IRREGULAR_PLURALS = {
    "category": "categories",
    "item": "items",
}


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
    envelope = _mcp_envelope(rows)
    if envelope is not None:
        status = str(envelope.get("status") or "")
        if envelope.get("ok") is True and status not in MCP_SOFT_STATUSES:
            answer_kind = "zero_rows" if not envelope.get("data") else "success"
        else:
            answer_kind = status or ("success" if envelope.get("ok") is True else "mcp_failed")
        return {
            "final_answer": format_mcp_result(state, envelope),
            "answer_kind": answer_kind,
            "current_node": "result_formatter",
            "status": "completed",
        }

    if kind == "zero_rows" or not rows:
        if wants_count_question(question):
            return {
                "final_answer": _count_answer(0, _resource_from_state(state)),
                "answer_kind": "zero_rows",
                "current_node": "result_formatter",
                "status": "completed",
            }
        return {
            "final_answer": "No matching records in the tables you allowed.",
            "answer_kind": "zero_rows",
            "current_node": "result_formatter",
            "status": "completed",
        }

    if not _use_llm_narrative(state, rows):
        return {
            "final_answer": deterministic_result_answer(
                rows,
                question=question,
                resource=_resource_from_state(state),
            ),
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
            "final_answer": deterministic_result_answer(
                rows,
                question=question,
                resource=_resource_from_state(state),
            ),
            "answer_kind": "success",
            "current_node": "result_formatter",
            "status": "completed",
        }

    final_answer = (final_answer or "").strip()
    if not final_answer:
        final_answer = deterministic_result_answer(
            rows,
            question=question,
            resource=_resource_from_state(state),
        )

    return {
        "final_answer": final_answer,
        "answer_kind": "success",
        "current_node": "result_formatter",
        "status": "completed",
    }


def format_mcp_result(state: QueryMindState, envelope: dict[str, Any]) -> str:
    status = str(envelope.get("status") or "")
    fallbacks = {
        "needs_confirmation": "That change needs confirmation before it will be applied.",
        "needs_parameters": "QueryMind needs a bit more information before it can continue.",
        "ambiguous": "Several records matched. Please be more specific.",
    }
    fallback = fallbacks.get(status, "")
    message = _safe_tool_message(envelope, fallback)
    if status in MCP_SOFT_STATUSES:
        return message or fallback
    if envelope.get("ok") is False:
        return message or "That request could not be completed."
    operation = str((state.operation_intent or {}).get("operation") or "").upper()
    if operation in WRITE_OPERATIONS:
        if envelope.get("ok") is True:
            return message or "The change was saved."
        return message or "That request could not be completed."
    items = _items_from_data(envelope.get("data"))
    resource = _resource_from_state(state)
    question = state.question or ""
    if wants_count_question(question):
        return _count_answer(len(items), resource)
    if items:
        return _list_answer(items, resource)
    return message or _count_answer(0, resource)


def _safe_tool_message(envelope: dict[str, Any], fallback: str) -> str:
    message = str(envelope.get("message") or "").strip()
    if message and _INJECTION_RE.search(message):
        return fallback
    return message


def deterministic_result_answer(
    rows: list[dict[str, Any]] | None,
    question: str = "",
    resource: str | None = None,
) -> str:
    rows = [row for row in (rows or []) if isinstance(row, dict)]
    if wants_count_question(question):
        scalar = _scalar_count(rows)
        count = scalar if scalar is not None else len(rows)
        return _count_answer(count, resource)
    if not rows:
        return "No matching records in the tables you allowed."
    return _list_answer(rows, resource)


def _use_llm_narrative(state: QueryMindState, rows: list[dict[str, Any]]) -> bool:
    if wants_count_question(state.question):
        return False
    if len(rows) >= 8:
        return False
    intent = state.intent or {}
    output = intent.get("output") or "row_list"
    if output == "row_list" or is_trivial_intent(intent):
        return False
    return output in {"scalar", "grouped"}


def _mcp_envelope(rows: list[Any]) -> dict[str, Any] | None:
    if not rows or not isinstance(rows[0], dict):
        return None
    row = rows[0]
    if row.get("status") and (row.get("message") is not None or "ok" in row):
        return row
    return None


def _resource_from_state(state: QueryMindState) -> str | None:
    operation = state.operation_intent or {}
    resource = operation.get("resource")
    if resource:
        return str(resource)
    intent = state.intent or {}
    return intent.get("entity") or intent.get("resource")


def _items_from_data(data: Any) -> list[dict[str, Any]]:
    if data is None:
        return []
    if isinstance(data, list):
        return [item if isinstance(item, dict) else {"value": item} for item in data]
    if isinstance(data, dict):
        return [data]
    return [{"value": data}]


def _scalar_count(rows: list[dict[str, Any]]) -> int | None:
    if len(rows) != 1:
        return None
    row = rows[0]
    for key in ("count", "total", "cnt"):
        if key in row:
            try:
                return int(row[key])
            except (TypeError, ValueError):
                return None
    if len(row) == 1:
        value = next(iter(row.values()))
        if isinstance(value, bool) or isinstance(value, str):
            return None
        if isinstance(value, (int, float)):
            return int(value)
    return None


def _count_answer(count: int, resource: str | None) -> str:
    noun = _pluralize(resource or "item", count)
    return f"You have {count} {noun}."


def _list_answer(items: list[dict[str, Any]], resource: str | None) -> str:
    noun = _pluralize(resource or "item", len(items))
    verb = "is" if len(items) == 1 else "are"
    header = f"Here {verb} your {noun}:"
    lines = [_format_record(item) for item in items]
    return header + "\n" + "\n".join(f"- {line}" for line in lines)


def _pluralize(noun: str, count: int) -> str:
    raw = (noun or "item").strip().lower()
    if count == 1:
        return raw
    if raw in _IRREGULAR_PLURALS:
        return _IRREGULAR_PLURALS[raw]
    if raw.endswith("y") and len(raw) > 1 and raw[-2] not in "aeiou":
        return raw[:-1] + "ies"
    if raw.endswith(("s", "x", "z", "ch", "sh")):
        return raw + "es"
    return raw + "s"


def _format_record(item: dict[str, Any]) -> str:
    title = _record_title(item)
    extras: list[str] = []
    for key, value in item.items():
        lowered = str(key).lower()
        if lowered in _HIDDEN_FIELDS or lowered in _TITLE_FIELDS:
            continue
        if value in (None, "", [], {}):
            continue
        extras.append(f"{str(key).replace('_', ' ')}: {_stringify(value)}")
    if title and extras:
        return f"{title} ({', '.join(extras)})"
    if title:
        return title
    if extras:
        return ", ".join(extras)
    ident = item.get("id")
    return str(ident) if ident not in (None, "") else "record"


def _record_title(item: dict[str, Any]) -> str | None:
    for key in _TITLE_FIELDS:
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(_format_record(item))
            else:
                parts.append(str(item))
        return "; ".join(parts)
    if isinstance(value, dict):
        return _format_record(value)
    return str(value)
