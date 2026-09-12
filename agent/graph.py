from langgraph.graph import END, START, StateGraph

from .state import QueryMindState

from .nodes.planner import planner
from .nodes.schema import schema, schema_shared_by_user
from .nodes.sql_generator import sql_generator, sql_generator_on_premise
from .nodes.sql_validator import sql_validator
from .nodes.sql_executor import sql_executor
from .nodes.error_analyzer import error_analyzer
from .nodes.sql_repair import sql_repair
from .nodes.result_formatter import result_formatter
from .nodes.refuse import refuse_answer


def route_after_api_validation(state: QueryMindState) -> str:
    result = state.validation_result or {}
    if result.get("valid"):
        return "validated"
    if result.get("fail_closed"):
        return "validated"
    if (state.sql_attempts or 0) >= (state.max_retries or 3):
        return "validated"
    return "repair"


def route_after_on_premise_validation(state: QueryMindState) -> str:
    result = state.validation_result or {}
    if result.get("valid"):
        return "execute"
    if result.get("fail_closed"):
        return "refuse"
    if (state.sql_attempts or 0) >= (state.max_retries or 3):
        return "refuse"
    return "repair"


def route_after_on_premise_execution(state: QueryMindState) -> str:
    execution = state.execution_result or {}
    if execution.get("success"):
        return "success"
    kind = execution.get("kind") or state.answer_kind
    if kind in {"unavailable", "connection_failed"}:
        return "refuse"
    return "error"


def route_after_on_premise_error_analysis(state: QueryMindState) -> str:
    analysis = state.error_analysis or {}
    action = analysis.get("action") or "end"
    if (state.retry_count or 0) >= (state.max_retries or 3):
        return "end"
    if action == "repair":
        return "repair"
    if action == "schema":
        return "schema"
    return "end"


def build_on_premise_graph():
    workflow = StateGraph(QueryMindState)

    workflow.add_node("planner", planner)
    workflow.add_node("schema", schema)
    workflow.add_node("sql_generator", sql_generator_on_premise)
    workflow.add_node("sql_validator", sql_validator)
    workflow.add_node("sql_executor", sql_executor)
    workflow.add_node("error_analyzer", error_analyzer)
    workflow.add_node("sql_repair", sql_repair)
    workflow.add_node("result_formatter", result_formatter)
    workflow.add_node("refuse", refuse_answer)

    workflow.add_edge(START, "planner")
    workflow.add_edge("planner", "schema")
    workflow.add_edge("schema", "sql_generator")
    workflow.add_edge("sql_generator", "sql_validator")

    workflow.add_conditional_edges(
        "sql_validator",
        route_after_on_premise_validation,
        {
            "execute": "sql_executor",
            "repair": "sql_repair",
            "refuse": "refuse",
        },
    )

    workflow.add_edge("sql_repair", "sql_validator")

    workflow.add_conditional_edges(
        "sql_executor",
        route_after_on_premise_execution,
        {
            "success": "result_formatter",
            "error": "error_analyzer",
            "refuse": "refuse",
        },
    )

    workflow.add_conditional_edges(
        "error_analyzer",
        route_after_on_premise_error_analysis,
        {
            "repair": "sql_repair",
            "schema": "schema",
            "end": "refuse",
        },
    )

    workflow.add_edge("result_formatter", END)
    workflow.add_edge("refuse", END)

    return workflow.compile()


def build_api_query_graph():
    workflow = StateGraph(QueryMindState)

    workflow.add_node("planner", planner)
    workflow.add_node("schema", schema_shared_by_user)
    workflow.add_node("sql_generator", sql_generator)
    workflow.add_node("sql_validator", sql_validator)
    workflow.add_node("sql_repair", sql_repair)

    workflow.add_edge(START, "planner")
    workflow.add_edge("planner", "schema")
    workflow.add_edge("schema", "sql_generator")
    workflow.add_edge("sql_generator", "sql_validator")

    workflow.add_conditional_edges(
        "sql_validator",
        route_after_api_validation,
        {
            "validated": END,
            "repair": "sql_repair",
        },
    )

    workflow.add_edge("sql_repair", "sql_validator")

    return workflow.compile()


def build_api_result_graph():
    workflow = StateGraph(QueryMindState)

    workflow.add_node("result_formatter", result_formatter)

    workflow.add_edge(START, "result_formatter")
    workflow.add_edge("result_formatter", END)

    return workflow.compile()
