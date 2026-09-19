# Understands failures
# Directly retry things


# agent/nodes/error_analyzer.py

from typing import Any

from ..state import QueryMindState


def error_analyzer(state: QueryMindState) -> dict[str, Any]:
    """
    Analyze a SQL/database execution error and determine the
    recovery strategy.

    This node does NOT decide the graph's next node. It only stores
    a recovery decision. Schema refresh is attempted at most once;
    repeating it with the same allow-list loops the chat UI.
    """
    result = _classify_error(state)
    analysis = dict(result.get("error_analysis") or {})
    action = analysis.get("action") or "end"
    previous = state.error_analysis or {}
    retry_count = int(state.retry_count or 0)
    if action == "schema" and previous.get("schema_retried"):
        analysis["action"] = "repair"
        action = "repair"
    if action == "schema":
        analysis["schema_retried"] = True
    elif previous.get("schema_retried"):
        analysis["schema_retried"] = True
    if action in {"repair", "schema"}:
        retry_count += 1
        result["retry_count"] = retry_count
    result["error_analysis"] = analysis
    return result


def _classify_error(state: QueryMindState) -> dict[str, Any]:
    error = (state.database_error or "").strip()

    # ============================================================
    # 1. No error available
    # ============================================================

    if not error:
        return {
            "error_analysis": {
                "error_type": "unknown",
                "recoverable": False,
                "action": "end",
                "reason": "No database error was provided.",
            },
            "current_node": "error_analyzer",
            "status": "failed",
        }

    error_lower = error.lower()

    # ============================================================
    # 2. PostgreSQL schema-related errors
    # ============================================================

    if _is_missing_column(error_lower):

        return {
            "error_analysis": {
                "error_type": "column_not_found",
                "recoverable": True,
                "action": "schema",
                "reason": (
                    "The generated SQL references a column that "
                    "does not exist in the current database schema."
                ),
            },
            "current_node": "error_analyzer",
            "status": "running",
        }

    if _is_missing_table(error_lower):

        return {
            "error_analysis": {
                "error_type": "table_not_found",
                "recoverable": True,
                "action": "schema",
                "reason": (
                    "The generated SQL references a table or "
                    "relation that does not exist."
                ),
            },
            "current_node": "error_analyzer",
            "status": "running",
        }

    if "schema" in error_lower and "does not exist" in error_lower:

        return {
            "error_analysis": {
                "error_type": "schema_not_found",
                "recoverable": True,
                "action": "schema",
                "reason": (
                    "The generated SQL references a database schema "
                    "that does not exist."
                ),
            },
            "current_node": "error_analyzer",
            "status": "running",
        }

    # ============================================================
    # 3. SQL syntax errors
    # ============================================================

    if "syntax error" in error_lower:

        return {
            "error_analysis": {
                "error_type": "syntax_error",
                "recoverable": True,
                "action": "repair",
                "reason": (
                    "PostgreSQL rejected the generated SQL because "
                    "of a syntax error."
                ),
            },
            "current_node": "error_analyzer",
            "status": "running",
        }

    # ============================================================
    # 4. Undefined function
    # ============================================================

    if "function" in error_lower and "does not exist" in error_lower:

        return {
            "error_analysis": {
                "error_type": "function_not_found",
                "recoverable": True,
                "action": "repair",
                "reason": (
                    "The generated SQL references a function that "
                    "PostgreSQL could not find."
                ),
            },
            "current_node": "error_analyzer",
            "status": "running",
        }

    # ============================================================
    # 5. Invalid operator
    # ============================================================

    if "operator does not exist" in error_lower:

        return {
            "error_analysis": {
                "error_type": "invalid_operator",
                "recoverable": True,
                "action": "repair",
                "reason": (
                    "The generated SQL uses an operator with "
                    "incompatible operand types."
                ),
            },
            "current_node": "error_analyzer",
            "status": "running",
        }

    # ============================================================
    # 6. Invalid data type
    # ============================================================

    if (
        "invalid input syntax for type" in error_lower
        or "datatype mismatch" in error_lower
    ):

        return {
            "error_analysis": {
                "error_type": "data_type_error",
                "recoverable": True,
                "action": "repair",
                "reason": (
                    "The generated SQL contains a value or "
                    "expression incompatible with the expected type."
                ),
            },
            "current_node": "error_analyzer",
            "status": "running",
        }

    # ============================================================
    # 7. Permission errors
    # ============================================================

    if "permission denied" in error_lower or "not enough privileges" in error_lower:

        return {
            "error_analysis": {
                "error_type": "permission_denied",
                "recoverable": False,
                "action": "end",
                "reason": (
                    "The database user does not have permission "
                    "to perform the requested operation."
                ),
            },
            "current_node": "error_analyzer",
            "status": "running",
        }

    # ============================================================
    # 8. Statement timeout
    # ============================================================

    if (
        "statement timeout" in error_lower
        or "canceling statement due to statement timeout" in error_lower
    ):

        return {
            "error_analysis": {
                "error_type": "statement_timeout",
                "recoverable": True,
                "action": "repair",
                "reason": (
                    "The query exceeded the configured database " "statement timeout."
                ),
            },
            "current_node": "error_analyzer",
            "status": "running",
        }

    # ============================================================
    # 9. Connection-related errors
    # ============================================================

    if any(
        keyword in error_lower
        for keyword in (
            "connection refused",
            "connection reset",
            "connection closed",
            "could not connect",
            "server closed the connection",
        )
    ):

        return {
            "error_analysis": {
                "error_type": "connection_error",
                "recoverable": True,
                "action": "end",
                "reason": (
                    "The database connection failed. "
                    "SQL repair cannot resolve a connection problem."
                ),
            },
            "current_node": "error_analyzer",
            "status": "running",
        }

    # ============================================================
    # 10. Unknown error
    # ============================================================

    return {
        "error_analysis": {
            "error_type": "unknown",
            "recoverable": False,
            "action": "end",
            "reason": ("The database error could not be safely classified."),
        },
        "current_node": "error_analyzer",
        "status": "running",
    }


def _is_missing_column(error_lower: str) -> bool:
    return (
        ("column" in error_lower and "does not exist" in error_lower)
        or "no such column" in error_lower
        or "unknown column" in error_lower
    )


def _is_missing_table(error_lower: str) -> bool:
    return (
        ("relation" in error_lower and "does not exist" in error_lower)
        or "no such table" in error_lower
        or ("table" in error_lower and "doesn't exist" in error_lower)
        or ("table" in error_lower and "does not exist" in error_lower)
    )
