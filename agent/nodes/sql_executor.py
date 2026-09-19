from typing import Any

from agent.operation import requested_result_limit_for_state
from connections.models import WorkspaceConnection
from connections.services.sql_validation import executor_for_workspace
from connections.services.fewshot import record_success

from ..state import QueryMindState


def sql_executor(state: QueryMindState) -> dict[str, Any]:
    sql = (state.sql or "").strip()
    allowed = list(state.allowed_tables or [])
    allowed_columns = dict(state.allowed_columns or {})
    requested_limit = requested_result_limit_for_state(state)

    if not allowed or not allowed_columns:
        return {
            "execution_result": {
                "success": False,
                "rows": [],
                "columns": [],
                "row_count": 0,
                "kind": "unavailable",
            },
            "database_error": "No allowed tables and columns. QueryMind will not run this query.",
            "answer_kind": "unavailable",
            "current_node": "sql_executor",
            "status": "failed",
        }

    if not sql:
        return {
            "execution_result": {
                "success": False,
                "rows": [],
                "columns": [],
                "row_count": 0,
                "kind": "error",
            },
            "database_error": "No SQL query available for execution.",
            "current_node": "sql_executor",
            "status": "running",
        }

    workspace = None
    if state.workspace_id:
        workspace = WorkspaceConnection.objects.filter(pk=state.workspace_id).first()
    if workspace is None:
        return {
            "execution_result": {
                "success": False,
                "rows": [],
                "columns": [],
                "row_count": 0,
                "kind": "connection_failed",
            },
            "database_error": "No database connection is configured for this workspace.",
            "answer_kind": "connection_failed",
            "current_node": "sql_executor",
            "status": "failed",
        }

    executor = executor_for_workspace(
        workspace,
        allowed,
        allowed_columns,
    )

    try:
        sql = executor.normalized_sql(sql, requested_limit=requested_limit)
        rows: list[dict[str, Any]] = []
        for row in executor.stream(sql, requested_limit=requested_limit):
            rows.append(row)
        columns = list(rows[0].keys()) if rows else []
        linked = list((state.intent or {}).get("tables") or state.allowed_tables or [])
        try:
            record_success(
                workspace_id=state.workspace_id,
                question=state.question,
                sql=sql,
                linked_tables=linked,
            )
        except Exception:
            pass
        return {
            "sql": sql,
            "execution_result": {
                "success": True,
                "rows": rows,
                "columns": columns,
                "row_count": len(rows),
                "kind": "zero_rows" if not rows else "success",
            },
            "database_error": None,
            "answer_kind": "zero_rows" if not rows else "success",
            "current_node": "sql_executor",
            "status": "running",
        }
    except PermissionError as exc:
        return {
            "execution_result": {
                "success": False,
                "rows": [],
                "columns": [],
                "row_count": 0,
                "kind": "unavailable",
            },
            "database_error": str(exc),
            "answer_kind": "unavailable",
            "current_node": "sql_executor",
            "status": "failed",
        }
    except Exception as exc:
        message = str(exc)
        kind = "connection_failed" if _is_connection_error(message) else "error"
        return {
            "execution_result": {
                "success": False,
                "rows": [],
                "columns": [],
                "row_count": 0,
                "kind": kind,
            },
            "database_error": message,
            "answer_kind": kind,
            "current_node": "sql_executor",
            "status": "running",
        }


def _is_connection_error(message: str) -> bool:
    lower = message.lower()
    return any(
        token in lower
        for token in (
            "connection refused",
            "could not connect",
            "connection timed out",
            "server closed the connection",
            "connection reset",
        )
    )
