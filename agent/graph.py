# Defines the state graph
# Contain business logic

# agent/graph.py

from langgraph.graph import END, START, StateGraph

from .state import QueryMindState

from .nodes.planner import planner
from .nodes.schema import schema, schema_shared_by_user
from .nodes.sql_generator import sql_generator
from .nodes.sql_validator import sql_validator
from .nodes.sql_executor import sql_executor
from .nodes.error_analyzer import error_analyzer
from .nodes.sql_repair import sql_repair
from .nodes.result_formatter import result_formatter

# from .edges.routing import (
#     route_after_validation,
#     route_after_execution,
#     route_after_error_analysis,
# )


def route_after_api_validation(state: QueryMindState) -> str:
    """
    Decide what happens after SQL validation in API mode.

    Returns:
        "validated" → SQL is valid, return it to the API client
        "repair"    → SQL is invalid, send it to the repair node
    """
    print("========== SQL VALIDATION ROUTE ==========")
    print("is_valid:", state.is_valid)
    print("sql:", state.sql)
    print("validation_error:", state.validation_error)
    print("==========================================")

    # if state.is_valid:
    #     return "validated"

    # return "repair"
    return "validated"


def route_after_on_premise_validation(state: QueryMindState) -> str:
    """
    Decide what happens after SQL validation in API mode.

    Returns:
        "validated" → SQL is valid, return it to the API client
        "repair"    → SQL is invalid, send it to the repair node
    """
    print("========== SQL VALIDATION ROUTE ==========")
    print("is_valid:", state.is_valid)
    print("sql:", state.sql)
    print("validation_error:", state.validation_error)
    print("==========================================")

    # if state.is_valid:
    #     return "validated"

    # return "repair"
    return "validated"


def route_after_on_premise_execution(state: QueryMindState) -> str:
    """
    Decide what happens after SQL validation in API mode.

    Returns:
        "validated" → SQL is valid, return it to the API client
        "repair"    → SQL is invalid, send it to the repair node
    """
    print("========== SQL VALIDATION ROUTE ==========")
    print("is_valid:", state.is_valid)
    print("sql:", state.sql)
    print("validation_error:", state.validation_error)
    print("==========================================")

    # if state.is_valid:
    #     return "validated"

    # return "repair"
    return "validated"


def route_after_on_premise_error_analysis(state: QueryMindState) -> str:
    """
    Decide what happens after SQL validation in API mode.

    Returns:
        "validated" → SQL is valid, return it to the API client
        "repair"    → SQL is invalid, send it to the repair node
    """
    print("========== SQL VALIDATION ROUTE ==========")
    print("is_valid:", state.is_valid)
    print("sql:", state.sql)
    print("validation_error:", state.validation_error)
    print("==========================================")

    # if state.is_valid:
    #     return "validated"

    # return "repair"
    return "validated"


def build_on_premise_graph():
    workflow = StateGraph(QueryMindState)

    workflow.add_node("planner", planner)
    workflow.add_node("schema", schema)
    workflow.add_node("sql_generator", sql_generator)
    workflow.add_node("sql_validator", sql_validator)
    workflow.add_node("sql_executor", sql_executor)
    workflow.add_node("error_analyzer", error_analyzer)
    workflow.add_node("sql_repair", sql_repair)
    workflow.add_node("result_formatter", result_formatter)

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
        },
    )

    workflow.add_edge("sql_repair", "sql_validator")

    workflow.add_conditional_edges(
        "sql_executor",
        route_after_on_premise_execution,
        {
            "success": "result_formatter",
            "error": "error_analyzer",
        },
    )

    workflow.add_conditional_edges(
        "error_analyzer",
        route_after_on_premise_error_analysis,
        {
            "repair": "sql_repair",
            "schema": "schema",
            "end": END,
        },
    )

    workflow.add_edge("result_formatter", END)

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
