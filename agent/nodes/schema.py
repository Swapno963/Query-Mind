# Gets relevant schema
# Decide overall workflow


# agent/nodes/schema.py

from typing import Any

from ..state import QueryMindState
from connections.services.schema_discovery import discover_schema


def schema(state: QueryMindState) -> dict[str, Any]:
    """
    Retrieve the database schema required by the current query.

    This node does NOT:
    - generate SQL
    - validate SQL
    - execute SQL
    - repair SQL
    - analyze database errors
    - decide the next graph node

    It only retrieves schema information and updates the agent state.
    """

    connection_id = state.connection_id

    try:
        # --------------------------------------------------------
        # Retrieve schema
        # --------------------------------------------------------

        discovered_schema = discover_schema(
            connection_id=connection_id,
        )

        # --------------------------------------------------------
        # Update state
        # --------------------------------------------------------

        return {
            "schema": discovered_schema,
            "current_node": "schema",
            "status": "running",
        }

    except Exception as exc:
        return {
            "database_error": str(exc),
            "current_node": "schema",
            "status": "failed",
        }


def schema_shared_by_user(state: QueryMindState) -> dict[str, Any]:
    """
    Retrieve the database schema required by the current query.

    This node does NOT:
    - generate SQL
    - validate SQL
    - execute SQL
    - repair SQL
    - analyze database errors
    - decide the next graph node

    It only retrieves schema information and updates the agent state.
    """

    connection_id = state.connection_id

    try:
        # --------------------------------------------------------
        # Retrieve schema
        # --------------------------------------------------------

        discovered_schema = discover_schema(
            connection_id=connection_id,
        )

        # --------------------------------------------------------
        # Update state
        # --------------------------------------------------------

        return {
            "schema": discovered_schema,
            "current_node": "schema",
            "status": "running",
        }

    except Exception as exc:
        return {
            "database_error": str(exc),
            "current_node": "schema",
            "status": "failed",
        }
