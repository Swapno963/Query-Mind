# Executes validated SQL
# Generate or repair SQL


# agent/nodes/sql_executor.py

from typing import Any

from connections.services.sql_validation import ReadOnlySQLExecutor

from ..state import QueryMindState


def sql_executor(state: QueryMindState) -> dict[str, Any]:
    """
    Execute validated SQL against the client database.

    This node is responsible only for:
    - reading validated SQL from state
    - executing the SQL
    - collecting query results
    - storing execution results in state
    - capturing database execution errors

    This node does NOT:
    - generate SQL
    - validate SQL
    - repair SQL
    - analyze errors
    - call Ollama
    - generate the final answer
    - save Django messages
    - handle SSE
    """

    sql = (state.sql or "").strip()

    # ============================================================
    # 1. Make sure SQL exists
    # ============================================================

    if not sql:
        return {
            "execution_result": {
                "success": False,
                "rows": [],
                "row_count": 0,
            },
            "database_error": "No SQL query available for execution.",
            "current_node": "sql_executor",
            "status": "running",
        }

    # ============================================================
    # 2. Make sure validation succeeded
    # ============================================================

    validation_result = state.validation_result

    if not validation_result.get("valid", False):
        return {
            "execution_result": {
                "success": False,
                "rows": [],
                "row_count": 0,
            },
            "database_error": ("SQL execution attempted before successful validation."),
            "current_node": "sql_executor",
            "status": "running",
        }

    # ============================================================
    # 3. Create read-only SQL executor
    # ============================================================

    executor = ReadOnlySQLExecutor(
        database="client",
    )

    try:
        # ========================================================
        # 4. Execute query
        #
        # stream() already performs:
        #
        # - validation
        # - read-only transaction
        # - statement timeout
        # - chunked fetching
        # - max row protection
        # ========================================================

        rows: list[dict[str, Any]] = []

        for row in executor.stream(sql):
            rows.append(row)

        # ========================================================
        # 5. Build execution result
        # ========================================================

        columns = []

        if rows:
            columns = list(rows[0].keys())

        execution_result = {
            "success": True,
            "rows": rows,
            "columns": columns,
            "row_count": len(rows),
        }

        # ========================================================
        # 6. Update state
        # ========================================================

        return {
            "execution_result": execution_result,
            "database_error": None,
            "current_node": "sql_executor",
            "status": "running",
        }

    except Exception as exc:

        # ========================================================
        # 7. Database execution failed
        # ========================================================

        return {
            "execution_result": {
                "success": False,
                "rows": [],
                "columns": [],
                "row_count": 0,
            },
            "database_error": str(exc),
            "current_node": "sql_executor",
            "status": "running",
        }
