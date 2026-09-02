# Defines agent execution state
# Execute anything
# agent/state.py

from typing import Any, TypedDict

from dataclasses import dataclass, field
from typing import Any

# ============================================================
# Planning
# ============================================================

intent: str | None = None
required_schema: list[str] = field(default_factory=list)
plan: dict[str, Any] = field(default_factory=dict)


@dataclass
class QueryMindState:
    question: str

    conversation_id: int
    message_id: int
    connection_id: int

    # ============================================================
    # Planning
    # ============================================================

    intent: str | None = None
    required_schema: list[str] = field(default_factory=list)
    plan: dict[str, Any] = field(default_factory=dict)

    schema: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 0

    conversation_context: str = ""

    sql: str | None = None
    sql_attempts: int = 0

    validation_result: dict[str, Any] = field(default_factory=dict)
    execution_result: dict[str, Any] = field(default_factory=dict)

    database_error: str | None = None
    error_analysis: dict[str, Any] = field(default_factory=dict)

    retry_count: int = 0
    max_retries: int = 3

    final_answer: str | None = None

    current_node: str | None = None
    status: str = "pending"
    is_valid: str | None = None
    validation_error: str | None = None
