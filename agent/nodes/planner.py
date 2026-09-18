from typing import Any

from connections.models import WorkspaceConnection
from connections.services.schema_discovery import extract_relationships_from_schema

from ..intent import (
    empty_intent,
    llm_intent,
    rule_based_intent,
)
from ..state import QueryMindState


def planner(state: QueryMindState) -> dict[str, Any]:
    question = (state.question or "").strip()
    if not question:
        return {
            "intent": empty_intent(),
            "plan": {"valid": False, "reason": "Question is empty."},
            "answer_kind": "unavailable",
            "database_error": "Question is empty.",
            "current_node": "planner",
            "status": "failed",
        }

    allowed = list(state.allowed_tables or [])
    allowed_columns = dict(state.allowed_columns or {})
    semantic_layer = dict(state.semantic_layer or {})
    workspace = None
    if state.workspace_id:
        workspace = WorkspaceConnection.objects.filter(pk=state.workspace_id).first()
    if workspace is not None:
        if not allowed:
            allowed = list(workspace.allowed_tables or [])
        if not allowed_columns:
            allowed_columns = dict(workspace.allowed_columns or {})
        if not semantic_layer:
            semantic_layer = dict(workspace.semantic_layer or {})

    schema_text = state.schema_text or (workspace.schema_text if workspace else "")
    relationships = extract_relationships_from_schema(schema_text)

    ir = rule_based_intent(
        question,
        allowed,
        allowed_columns,
        semantic_layer,
    )
    if ir is None or not ir.get("valid"):
        try:
            ir = llm_intent(
                question,
                schema_text,
                state.conversation_context,
                allowed,
                allowed_columns,
                semantic_layer,
                backend=getattr(state, "llm_backend", "local") or "local",
            )
        except Exception:
            ir = ir or empty_intent()
            ir["valid"] = False

    if not ir or not ir.get("valid"):
        return {
            "intent": ir or empty_intent(),
            "grain": "",
            "plan": {"valid": False, "reason": (ir or {}).get("reason") or "Could not plan."},
            "allowed_tables": allowed,
            "allowed_columns": allowed_columns,
            "semantic_layer": semantic_layer,
            "relationships": relationships,
            "answer_kind": "unavailable",
            "database_error": (ir or {}).get("reason") or "Could not plan a safe query.",
            "current_node": "planner",
            "status": "failed",
        }

    return {
        "intent": ir,
        "grain": ir.get("grain") or "",
        "required_schema": list(ir.get("tables") or []),
        "plan": {
            "valid": True,
            "operation": "read",
            "requires_schema": True,
            "output": ir.get("output"),
        },
        "allowed_tables": allowed,
        "allowed_columns": allowed_columns,
        "semantic_layer": semantic_layer,
        "relationships": relationships,
        "current_node": "planner",
        "status": "running",
    }
