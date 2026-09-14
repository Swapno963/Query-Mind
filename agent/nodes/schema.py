import json
from typing import Any

from connections.models import WorkspaceConnection
from connections.services.prompt import PromptGenerator, SelectedSchema
from connections.services.schema_discovery import filter_schema_to_tables
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

    question = (state.question or "").strip()
    try:
        prompt_generator = PromptGenerator()
        prompt = prompt_generator.generate_schema_selection_prompt(
            question=question,
            schema=allowed_schema,
            conversation_context=state.conversation_context,
        )
        discovered_schema = ChatService.ask_on_premise_ai(prompt)
        selected_schema = json.loads(_extract_json(discovered_schema))
        selected_text = SelectedSchema.build_relevant_schema(
            selected_schema,
            allowed_schema,
        )
        schema_text = selected_text or allowed_schema
        return {
            "schema": schema_text,
            "schema_text": allowed_schema,
            "allowed_tables": allowed,
            "allowed_columns": allowed_columns,
            "current_node": "schema",
            "status": "running",
        }
    except Exception:
        return {
            "schema": allowed_schema,
            "schema_text": allowed_schema,
            "allowed_tables": allowed,
            "allowed_columns": allowed_columns,
            "current_node": "schema",
            "status": "running",
        }


def schema_shared_by_user(state: QueryMindState) -> dict[str, Any]:
    return schema(state)


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
