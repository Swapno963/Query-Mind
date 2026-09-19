from typing import Any

import httpx

from connections.services.fewshot import retrieve_examples
from connections.services.prompt import PromptGenerator
from connections.services.sql_critic import rank_sql_candidates
from connections.services.engines import sql_language_name, sqlglot_dialect
from agent.llm import ask_state
from ..intent import is_hard_query

from ..state import QueryMindState


def _sql_system(engine: str) -> str:
    language = sql_language_name(engine)
    return f"You emit a single {language} SELECT statement. No markdown, no commentary."


def sql_generator(state: QueryMindState) -> dict[str, Any]:
    return _generate(state)


def sql_generator_on_premise(state: QueryMindState) -> dict[str, Any]:
    return _generate(state)


def _generate(state: QueryMindState) -> dict[str, Any]:
    question = (state.question or "").strip()
    if not question:
        return {
            "database_error": "Question cannot be empty.",
            "current_node": "sql_generator",
            "status": "failed",
        }

    if state.answer_kind in {"unavailable", "connection_failed"}:
        return {
            "sql": None,
            "database_error": state.database_error
            or "QueryMind will not run this query.",
            "current_node": "sql_generator",
            "status": "failed",
        }

    schema_blob = state.schema or state.schema_text
    if not schema_blob:
        return {
            "sql": None,
            "database_error": "No allowed tables. QueryMind will not run this query.",
            "answer_kind": "unavailable",
            "current_node": "sql_generator",
            "status": "failed",
        }

    try:
        examples = retrieve_examples(
            workspace_id=state.workspace_id,
            question=question,
            allowed_tables=list(state.allowed_tables or []),
        )
        prompt = PromptGenerator().generate(
            question=question,
            schema=schema_blob,
            conversation_context=state.conversation_context,
            intent=state.intent,
            examples=examples,
            sql_language=sql_language_name(state.engine),
        )
        backend = (getattr(state, "llm_backend", None) or "local").strip().lower()
        local = backend != "online"
        system = _sql_system(state.engine)
        kwargs = {"temperature": 0.05, "system": system} if local else {}
        primary = _clean_sql(ask_state(state, prompt, **kwargs))
        candidates = [primary] if primary else []
        need_more = is_hard_query(state.intent) or bool(
            (state.critic_result or {}).get("issues")
            or (state.explain_result or {}).get("ok") is False
        )
        if local and need_more:
            for _ in range(2):
                extra = _clean_sql(
                    ask_state(
                        state,
                        prompt,
                        temperature=0.3,
                        system=system,
                    )
                )
                if extra and extra not in candidates:
                    candidates.append(extra)
        sql = rank_sql_candidates(
            candidates,
            intent=state.intent,
            relationships=state.relationships,
            allowed_tables=state.allowed_tables,
            dialect=sqlglot_dialect(state.engine),
        ) or primary
        if not sql:
            return {
                "database_error": "LLM returned an empty SQL query.",
                "current_node": "sql_generator",
                "status": "failed",
            }
        return {
            "sql": sql,
            "sql_candidates": candidates,
            "sql_attempts": state.sql_attempts + 1,
            "database_error": None,
            "current_node": "sql_generator",
            "status": "running",
        }
    except httpx.HTTPError as exc:
        return {
            "database_error": f"LLM request failed: {exc}",
            "current_node": "sql_generator",
            "status": "failed",
        }
    except Exception as exc:
        return {
            "database_error": str(exc),
            "current_node": "sql_generator",
            "status": "failed",
        }


def _clean_sql(sql: str) -> str:
    sql = (sql or "").strip()
    if sql.startswith("```sql"):
        sql = sql[6:]
    elif sql.startswith("```"):
        sql = sql[3:]
    if sql.endswith("```"):
        sql = sql[:-3]
    return sql.strip()
