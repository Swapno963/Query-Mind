from typing import Any

from connections.models import WorkspaceConnection
from connections.services.workspace import register_workspace_database
from connections.services.sql_validation import ReadOnlySQLExecutor

from ..state import QueryMindState


def sql_executor(state: QueryMindState) -> dict[str, Any]:
    sql = (state.sql or "").strip()
    allowed = list(state.allowed_tables or [])

    if not allowed:
        return {
            "execution_result": {
                "success": False,
                "rows": [],
                "columns": [],
                "row_count": 0,
                "kind": "unavailable",
            },
            "database_error": "No allowed tables. QueryMind will not run this query.",
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

    alias = register_workspace_database(workspace)
    executor = ReadOnlySQLExecutor(
        database=alias,
        allowed_tables=set(allowed),
    )

    try:
        executor.validate(sql)
        rows: list[dict[str, Any]] = []
        for row in executor.stream(sql):
            rows.append(row)
        columns = list(rows[0].keys()) if rows else []
        return {
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
