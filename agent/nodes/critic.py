import json
from typing import Any

from chat.api.chat_service import ChatService
from connections.services.sql_critic import critique_sql
from connections.services.engines import sqlglot_dialect
from ..intent import is_trivial_intent

from ..state import QueryMindState


def sql_critic(state: QueryMindState) -> dict[str, Any]:
    sql = state.sql or ""
    intent = state.intent or {}
    result = critique_sql(
        sql,
        intent=intent,
        relationships=state.relationships or [],
        allowed_tables=state.allowed_tables or [],
        dialect=sqlglot_dialect(state.engine),
    )
    if result.get("ok") and not is_trivial_intent(intent):
        metric = intent.get("metric") or {}
        joins = intent.get("joins") or []
        tables = intent.get("tables") or []
        hard = bool(metric and (joins or len(tables) > 1))
        if hard:
            result = _llm_critic(state, result)

    ok = bool(result.get("ok"))
    issues = result.get("issues") or []
    error = None if ok else "; ".join(issues) or "SQL failed semantic checks."
    return {
        "critic_result": result,
        "database_error": error,
        "validation_error": error,
        "is_valid": ok,
        "answer_kind": None if ok else "invalid_sql",
        "current_node": "sql_critic",
        "status": "running",
    }


def _llm_critic(state: QueryMindState, base: dict[str, Any]) -> dict[str, Any]:
    prompt = f"""
Score whether this SQL implements the intent without changing grain.

QUESTION:
{state.question}

INTENT:
{json.dumps(state.intent or {}, indent=2, default=str)}

GRAIN:
{state.grain}

SQL:
{state.sql}

Return JSON only: {{"ok": true, "issues": [], "confidence": 0.0}}
Flag fan_out_on_sum, wrong_filter, wrong_grain, missing_time_filter.
""".strip()
    try:
        raw = ChatService.ask_on_premise_ai(
            prompt,
            temperature=0.0,
            system="You emit JSON only.",
        )
        start = raw.find("{")
        end = raw.rfind("}")
        parsed = json.loads(raw[start : end + 1]) if start >= 0 and end > start else {}
        if not isinstance(parsed, dict):
            return base
        issues = list(base.get("issues") or [])
        for item in parsed.get("issues") or []:
            if item not in issues:
                issues.append(str(item))
        ok = bool(parsed.get("ok", True)) and not issues
        return {
            "ok": ok,
            "issues": issues,
            "confidence": parsed.get("confidence", base.get("confidence")),
            "tables": base.get("tables") or [],
        }
    except Exception:
        return base
