# Understands failures
# Directly retry things


# agent/nodes/error_analyzer.py

from typing import Any

from ..state import QueryMindState


def error_analyzer(state: QueryMindState) -> dict[str, Any]:
    """
    Analyze a SQL/database execution error and determine the
    recovery strategy.

    This node does NOT:
    - execute SQL
    - generate SQL
    - repair SQL
    - call Ollama
    - modify the database
    - decide the graph's next node

    It only analyzes the error and stores a recovery decision
    in QueryMindState.
    """

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

    if "column" in error_lower and "does not exist" in error_lower:

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

    if "relation" in error_lower and "does not exist" in error_lower:

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
