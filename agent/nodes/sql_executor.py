# Executes validated SQL
# Generate or repair SQL


# agent/nodes/sql_executor.py

from typing import Any

from connections.services.sql_validation import ReadOnlySQLExecutor

from ..state import QueryMindState


def sql_executor(state: QueryMindState) -> dict[str, Any]:
    """
    Execute validated SQL against the client database.
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
                "columns": [],
                "row_count": 0,
            },
            "database_error": "No SQL query available for execution.",
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
        # 4. Validate SQL using the actual database executor
        # ========================================================

        executor.validate(sql)

        # ========================================================
        # 5. Execute SQL
        # ========================================================

        rows: list[dict[str, Any]] = []

        print("Executing SQL:")
        print(sql)

        for row in executor.stream(sql):
            rows.append(row)

        # ========================================================
        # 6. Extract columns
        # ========================================================

        columns = []

        if rows:
            columns = list(rows[0].keys())

        # ========================================================
        # 7. Build execution result
        # ========================================================
        execution_result = {
            "success": True,
            "rows": rows,
            "columns": columns,
            "row_count": len(rows),
        }
        print("execution_result : ", execution_result)

        # ========================================================
        # 8. Update state
        # ========================================================

        return {
            "execution_result": execution_result,
            "database_error": None,
            "current_node": "sql_executor",
            "status": "running",
        }

    except Exception as exc:

        # ========================================================
        # 9. Database execution failed
        # ========================================================

        print("SQL execution failed:")
        print(f"Error type: {type(exc).__name__}")
        print(f"Error message: {exc}")

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
