import json
from typing import Any

from connections.models import WorkspaceConnection
from connections.services.prompt import PromptGenerator, SelectedSchema
from connections.services.schema_discovery import (
    extract_relationships_from_schema,
    filter_schema_to_tables,
)
from chat.api.chat_service import ChatService

from ..state import QueryMindState


def schema(state: QueryMindState) -> dict[str, Any]:
    workspace = None
    if state.workspace_id:
        workspace = WorkspaceConnection.objects.filter(pk=state.workspace_id).first()

    allowed = list(state.allowed_tables or [])
    allowed_columns = dict(state.allowed_columns or {})
    if workspace is not None:
        if not allowed:
            allowed = list(workspace.allowed_tables or [])
        if not allowed_columns:
            allowed_columns = dict(workspace.allowed_columns or {})

    if not allowed or not allowed_columns:
        return {
            "database_error": "No allowed tables and columns. QueryMind will not run this query.",
            "answer_kind": "unavailable",
            "current_node": "schema",
            "status": "failed",
        }

    source_schema = state.schema_text or (workspace.schema_text if workspace else "")
    allowed_schema = filter_schema_to_tables(
        source_schema,
        allowed,
        allowed_columns,
    )
    if not allowed_schema:
        return {
            "database_error": "No allowed tables. QueryMind will not run this query.",
            "answer_kind": "unavailable",
            "current_node": "schema",
            "status": "failed",
        }

    fallback = _intent_fallback_schema(
        state.intent or {},
        allowed_schema,
        allowed_columns,
    ) or allowed_schema
    relationships = extract_relationships_from_schema(allowed_schema)

    question = (state.question or "").strip()
    selected_text = ""
    last_error = None
    for _ in range(2):
        try:
            prompt_generator = PromptGenerator()
            prompt = prompt_generator.generate_schema_selection_prompt(
                question=question,
                schema=allowed_schema,
                conversation_context=state.conversation_context,
                intent=state.intent,
            )
            discovered_schema = ChatService.ask_on_premise_ai(
                prompt,
                temperature=0.1,
                system="You emit JSON only.",
            )
            selected_schema = json.loads(_extract_json(discovered_schema))
            selected_schema = _intersect_selection(
                selected_schema,
                allowed,
                allowed_columns,
                relationships,
            )
            selected_text = SelectedSchema.build_relevant_schema(
                selected_schema,
                allowed_schema,
            )
            if selected_text:
                break
        except Exception as exc:
            last_error = exc
            selected_text = ""

    schema_text = selected_text or fallback
    return {
        "schema": schema_text,
        "schema_text": allowed_schema,
        "allowed_tables": allowed,
        "allowed_columns": allowed_columns,
        "relationships": relationships,
        "database_error": None if schema_text else str(last_error or "Schema linking failed."),
        "current_node": "schema",
        "status": "running" if schema_text else "failed",
        "answer_kind": None if schema_text else "unavailable",
    }


def schema_shared_by_user(state: QueryMindState) -> dict[str, Any]:
    return schema(state)


def _intersect_selection(
    selected_schema: dict,
    allowed_tables: list[str],
    allowed_columns: dict[str, list[str]],
    relationships: list[dict[str, str]],
) -> dict:
    allowed = {str(name).lower(): name for name in allowed_tables}
    columns = {
        str(table).lower(): {str(col).lower(): col for col in (cols or [])}
        for table, cols in (allowed_columns or {}).items()
    }
    raw_tables = (selected_schema or {}).get("tables") or {}
    cleaned: dict[str, list[str]] = {}
    for table, cols in raw_tables.items():
        key = str(table).lower()
        if key not in allowed:
            continue
        allowed_cols = columns.get(key) or {}
        kept = []
        for col in cols or []:
            col_key = str(col).lower()
            if col_key in allowed_cols:
                kept.append(allowed_cols[col_key])
        if kept:
            cleaned[allowed[key]] = kept
    selected_names = {name.lower() for name in cleaned}
    for rel in relationships:
        left = rel["source_table"].lower()
        right = rel["target_table"].lower()
        if left in selected_names and right in selected_names:
            for table, column in (
                (rel["source_table"], rel["source_column"]),
                (rel["target_table"], rel["target_column"]),
            ):
                key = table.lower()
                real_table = allowed.get(key)
                real_col = (columns.get(key) or {}).get(column.lower())
                if real_table and real_col:
                    bucket = cleaned.setdefault(real_table, [])
                    if real_col not in bucket:
                        bucket.append(real_col)
    return {"tables": cleaned}


def _intent_fallback_schema(
    intent: dict,
    allowed_schema: str,
    allowed_columns: dict[str, list[str]],
) -> str:
    tables = list(intent.get("tables") or [])
    entity = intent.get("entity")
    if entity and entity not in tables:
        tables.append(entity)
    if not tables:
        return ""
    return filter_schema_to_tables(allowed_schema, tables, allowed_columns)


def _extract_json(text: str) -> str:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        return raw[start : end + 1]
    return raw
