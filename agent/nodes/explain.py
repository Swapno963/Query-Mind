from typing import Any

from connections.models import WorkspaceConnection

from ..state import QueryMindState


def explain_sql(state: QueryMindState) -> dict[str, Any]:
    sql = state.sql or ""
    allowed = {str(name).lower() for name in (state.allowed_tables or []) if name}
    allowed_columns = dict(state.allowed_columns or {})
    if not allowed or not allowed_columns:
        return _explain_invalid(
            "No allowed tables and columns. QueryMind will not run this query.",
            fail_closed=True,
            kind="unavailable",
        )

    workspace = None
    if state.workspace_id:
        workspace = WorkspaceConnection.objects.filter(pk=state.workspace_id).first()
    if workspace is None:
        return {
            "explain_result": {"ok": True, "skipped": True},
            "current_node": "explain_sql",
            "status": "running",
        }

    from connections.services.sql_validation import executor_for_workspace

    executor = executor_for_workspace(
        workspace,
        allowed,
        allowed_columns,
    )
    try:
        result = executor.explain(sql)
        return {
            "explain_result": result,
            "database_error": None,
            "current_node": "explain_sql",
            "status": "running",
        }
    except PermissionError as exc:
        return _explain_invalid(str(exc), fail_closed=True, kind="unavailable")
    except Exception as exc:
        return _explain_invalid(str(exc), fail_closed=False, kind="invalid_sql")


def _explain_invalid(error: str, *, fail_closed: bool, kind: str) -> dict[str, Any]:
    return {
        "explain_result": {
            "ok": False,
            "error": error,
            "fail_closed": fail_closed,
            "kind": kind,
        },
        "validation_result": {
            "valid": False,
            "error": error,
            "fail_closed": fail_closed,
            "kind": kind,
        },
        "is_valid": False,
        "validation_error": error,
        "database_error": error,
        "answer_kind": kind if fail_closed else None,
        "current_node": "explain_sql",
        "status": "running",
    }
