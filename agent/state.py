# Defines agent execution state

from dataclasses import dataclass, field
from typing import Any


@dataclass
class QueryMindState:
    question: str

    conversation_id: int
    message_id: int
    connection_id: int

    intent: dict[str, Any] = field(default_factory=dict)
    required_schema: list[str] = field(default_factory=list)
    plan: dict[str, Any] = field(default_factory=dict)
    grain: str = ""

    schema: dict[str, Any] | str = field(default_factory=dict)
    schema_version: int = 0
    schema_text: str = ""
    allowed_tables: list[str] = field(default_factory=list)
    allowed_columns: dict[str, list[str]] = field(default_factory=dict)
    workspace_id: int | None = None
    engine: str = "postgres"
    semantic_layer: dict[str, Any] = field(default_factory=dict)
    relationships: list[dict[str, str]] = field(default_factory=list)

    conversation_context: str = ""

    sql: str | None = None
    sql_attempts: int = 0
    sql_candidates: list[str] = field(default_factory=list)

    validation_result: dict[str, Any] = field(default_factory=dict)
    execution_result: dict[str, Any] = field(default_factory=dict)
    explain_result: dict[str, Any] = field(default_factory=dict)
    critic_result: dict[str, Any] = field(default_factory=dict)

    database_error: str | None = None
    error_analysis: dict[str, Any] = field(default_factory=dict)

    retry_count: int = 0
    max_retries: int = 3

    final_answer: str | None = None
    answer_kind: str | None = None

    current_node: str | None = None
    status: str = "pending"
    is_valid: bool | None = None
    validation_error: str | None = None
