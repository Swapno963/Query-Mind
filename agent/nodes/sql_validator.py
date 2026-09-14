from typing import Any

from connections.services.sql_validation import ReadOnlySQLExecutor
from chat.api.chat_service import SQLFallbackInterceptor

from ..state import QueryMindState


def sql_validator(state: QueryMindState) -> dict[str, Any]:
    allowed = {str(name).lower() for name in (state.allowed_tables or []) if name}
    allowed_columns = dict(state.allowed_columns or {})
    sql = state.sql or ""

    if not allowed or not allowed_columns:
        error = "No allowed tables and columns. QueryMind will not run this query."
        return _invalid(
            error,
            fail_closed=True,
            kind="unavailable",
        )

    try:
        is_fallback, fallback_reason = SQLFallbackInterceptor.analyze_query(
            sql=sql,
            allowed_tables=allowed,
        )
    except Exception as exc:
        return _invalid(str(exc), fail_closed=True, kind="error")

    if is_fallback:
        return _invalid(
            fallback_reason or "This question cannot be answered from your allowed tables.",
            fail_closed=True,
            kind="unavailable",
        )

    try:
        ReadOnlySQLExecutor(
            allowed_tables=allowed,
            allowed_columns=allowed_columns,
        ).validate(sql)
    except PermissionError as exc:
        return _invalid(str(exc), fail_closed=True, kind="unavailable")
    except ValueError as exc:
        return _invalid(str(exc), fail_closed=False, kind="invalid_sql")
    except Exception as exc:
        return _invalid(str(exc), fail_closed=False, kind="invalid_sql")

    return {
        "validation_result": {
            "valid": True,
            "error": None,
            "fail_closed": False,
            "kind": "ok",
        },
        "is_valid": True,
        "validation_error": None,
        "database_error": None,
        "current_node": "sql_validator",
        "status": "running",
    }


def _invalid(error: str, *, fail_closed: bool, kind: str) -> dict[str, Any]:
    return {
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
        "current_node": "sql_validator",
        "status": "running",
    }
