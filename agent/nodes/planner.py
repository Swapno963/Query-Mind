# Understands what needs to happen
# Execute SQL / control graph


# agent/nodes/planner.py

from typing import Any

from ..state import QueryMindState


def planner(state: QueryMindState) -> dict[str, Any]:
    """
    Analyze the user's question and create a high-level plan.

    This node does NOT:
    - generate SQL
    - query the database
    - retrieve schema
    - validate SQL
    - execute SQL
    - decide the next graph node

    It only analyzes the question and updates the agent state.
    """

    question = state.question.strip()

    if not question:
        return {
            "intent": "invalid",
            "required_schema": [],
            "plan": {
                "valid": False,
                "reason": "Question is empty.",
            },
            "current_node": "planner",
            "status": "failed",
        }

    # ------------------------------------------------------------
    # Initial planner implementation
    #
    # For now, keep planning deterministic.
    # We will replace/extend this with structured LLM planning.
    # ------------------------------------------------------------

    plan = {
        "valid": True,
        "operation": "read",
        "requires_schema": True,
    }

    return {
        "intent": "database_query",
        "required_schema": [],
        "plan": plan,
        "current_node": "planner",
        "status": "running",
    }
