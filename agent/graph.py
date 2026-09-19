from langgraph.graph import END, START, StateGraph

from .state import QueryMindState
from .nodes.planner import planner
from .nodes.schema import schema, schema_shared_by_user
from .nodes.sql_generator import sql_generator, sql_generator_on_premise
from .nodes.sql_validator import sql_validator
from .nodes.explain import explain_sql
from .nodes.critic import sql_critic
from .nodes.sql_executor import sql_executor
from .nodes.error_analyzer import error_analyzer
from .nodes.sql_repair import sql_repair
from .nodes.result_formatter import result_formatter
from .nodes.refuse import refuse_answer
from .nodes.classify import classify_operation
from .nodes.policy import policy_check
from .nodes.capability import capability_resolve
from .nodes.mcp_executor import mcp_execute
from .nodes.converse import converse_answer

GRAPH_RECURSION_LIMIT = 40
GRAPH_RUN_CONFIG = {"recursion_limit": GRAPH_RECURSION_LIMIT}


def route_after_classify(state: QueryMindState) -> str:
    if state.execution_mode == "converse":
        return "converse"
    if state.execution_mode in {"clarify", "deny"} or state.status == "failed":
        return "refuse"
    return "policy"


def route_after_policy(state: QueryMindState) -> str:
    if state.execution_mode == "deny" or state.status == "failed":
        return "refuse"
    return "capability"


def route_after_capability(state: QueryMindState) -> str:
    mode = state.execution_mode
    if mode == "mcp":
        return "mcp"
    if mode == "sql":
        return "planner"
    return "refuse"


def route_after_mcp_execute(state: QueryMindState) -> str:
    execution = state.execution_result or {}
    if execution.get("success"):
        return "format"
    return "refuse"


def route_after_planner(state: QueryMindState) -> str:
    if state.status == "failed" or (state.intent or {}).get("valid") is False:
        return "refuse"
    return "schema"


def route_after_schema(state: QueryMindState) -> str:
    if state.status == "failed" or state.answer_kind == "unavailable":
        return "refuse"
    return "generate"


def route_after_api_validation(state: QueryMindState) -> str:
    result = state.validation_result or {}
    if result.get("valid"):
        return "critic"
    if result.get("fail_closed"):
        return "validated"
    if (state.sql_attempts or 0) >= (state.max_retries or 3):
        return "validated"
    return "repair"


def route_after_on_premise_validation(state: QueryMindState) -> str:
    result = state.validation_result or {}
    if result.get("valid"):
        return "explain"
    if result.get("fail_closed"):
        return "refuse"
    if (state.sql_attempts or 0) >= (state.max_retries or 3):
        return "refuse"
    return "repair"


def route_after_explain(state: QueryMindState) -> str:
    result = state.explain_result or {}
    if result.get("ok") or result.get("skipped"):
        return "critic"
    if result.get("fail_closed"):
        return "refuse"
    if (state.sql_attempts or 0) >= (state.max_retries or 3):
        return "refuse"
    return "repair"


def route_after_on_premise_critic(state: QueryMindState) -> str:
    result = state.critic_result or {}
    if result.get("ok"):
        return "execute"
    if (state.sql_attempts or 0) >= (state.max_retries or 3):
        return "refuse"
    return "repair"


def route_after_api_critic(state: QueryMindState) -> str:
    result = state.critic_result or {}
    if result.get("ok"):
        return "validated"
    if (state.sql_attempts or 0) >= (state.max_retries or 3):
        return "validated"
    return "repair"


def route_after_on_premise_execution(state: QueryMindState) -> str:
    execution = state.execution_result or {}
    if execution.get("success"):
        return "success"
    kind = execution.get("kind") or state.answer_kind
    if kind in {"unavailable", "connection_failed"}:
        return "refuse"
    return "error"


def retry_budget_used(state: QueryMindState) -> int:
    return max(int(state.retry_count or 0), int(state.sql_attempts or 0))


def retries_exhausted(state: QueryMindState) -> bool:
    return retry_budget_used(state) >= int(state.max_retries or 3)


def route_after_on_premise_error_analysis(state: QueryMindState) -> str:
    analysis = state.error_analysis or {}
    action = analysis.get("action") or "end"
    if retries_exhausted(state):
        return "end"
    if action == "schema" and (
        analysis.get("schema_retried") and (state.retry_count or 0) > 1
    ):
        action = "repair"
    if action == "repair":
        return "repair"
    if action == "schema":
        return "schema"
    return "end"


def _add_control_nodes(workflow):
    workflow.add_node("classify_operation", classify_operation)
    workflow.add_node("policy_check", policy_check)
    workflow.add_node("capability_resolve", capability_resolve)
    workflow.add_node("mcp_execute", mcp_execute)
    workflow.add_node("converse", converse_answer)
    workflow.add_node("refuse", refuse_answer)
    workflow.add_edge(START, "classify_operation")
    workflow.add_conditional_edges(
        "classify_operation",
        route_after_classify,
        {"policy": "policy_check", "refuse": "refuse", "converse": "converse"},
    )
    workflow.add_conditional_edges(
        "policy_check",
        route_after_policy,
        {"capability": "capability_resolve", "refuse": "refuse"},
    )
    workflow.add_conditional_edges(
        "capability_resolve",
        route_after_capability,
        {"mcp": "mcp_execute", "planner": "planner", "refuse": "refuse"},
    )


def build_on_premise_graph():
    return _build_chat_graph(on_premise=True)


def build_online_graph():
    return _build_chat_graph(on_premise=False)


def _build_chat_graph(*, on_premise: bool):
    workflow = StateGraph(QueryMindState)

    workflow.add_node("planner", planner)
    workflow.add_node("schema", schema)
    workflow.add_node(
        "sql_generator",
        sql_generator_on_premise if on_premise else sql_generator,
    )
    workflow.add_node("sql_validator", sql_validator)
    workflow.add_node("explain_sql", explain_sql)
    workflow.add_node("sql_critic", sql_critic)
    workflow.add_node("sql_executor", sql_executor)
    workflow.add_node("error_analyzer", error_analyzer)
    workflow.add_node("sql_repair", sql_repair)
    workflow.add_node("result_formatter", result_formatter)
    _add_control_nodes(workflow)

    workflow.add_conditional_edges(
        "mcp_execute",
        route_after_mcp_execute,
        {"format": "result_formatter", "refuse": "refuse"},
    )
    workflow.add_conditional_edges(
        "planner",
        route_after_planner,
        {"schema": "schema", "refuse": "refuse"},
    )
    workflow.add_conditional_edges(
        "schema",
        route_after_schema,
        {"generate": "sql_generator", "refuse": "refuse"},
    )
    workflow.add_edge("sql_generator", "sql_validator")

    workflow.add_conditional_edges(
        "sql_validator",
        route_after_on_premise_validation,
        {
            "explain": "explain_sql",
            "repair": "sql_repair",
            "refuse": "refuse",
        },
    )
    workflow.add_conditional_edges(
        "explain_sql",
        route_after_explain,
        {
            "critic": "sql_critic",
            "repair": "sql_repair",
            "refuse": "refuse",
        },
    )
    workflow.add_conditional_edges(
        "sql_critic",
        route_after_on_premise_critic,
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
    workflow.add_edge("converse", END)
    workflow.add_edge("refuse", END)

    return workflow.compile()


def build_api_query_graph():
    workflow = StateGraph(QueryMindState)

    workflow.add_node("planner", planner)
    workflow.add_node("schema", schema_shared_by_user)
    workflow.add_node("sql_generator", sql_generator)
    workflow.add_node("sql_validator", sql_validator)
    workflow.add_node("sql_critic", sql_critic)
    workflow.add_node("sql_repair", sql_repair)
    workflow.add_node("result_formatter", result_formatter)
    _add_control_nodes(workflow)

    workflow.add_conditional_edges(
        "mcp_execute",
        route_after_mcp_execute,
        {"format": "result_formatter", "refuse": "refuse"},
    )
    workflow.add_conditional_edges(
        "planner",
        route_after_planner,
        {"schema": "schema", "refuse": "refuse"},
    )
    workflow.add_conditional_edges(
        "schema",
        route_after_schema,
        {"generate": "sql_generator", "refuse": "refuse"},
    )
    workflow.add_edge("sql_generator", "sql_validator")

    workflow.add_conditional_edges(
        "sql_validator",
        route_after_api_validation,
        {
            "critic": "sql_critic",
            "repair": "sql_repair",
            "validated": END,
        },
    )
    workflow.add_conditional_edges(
        "sql_critic",
        route_after_api_critic,
        {
            "validated": END,
            "repair": "sql_repair",
        },
    )

    workflow.add_edge("sql_repair", "sql_validator")
    workflow.add_edge("result_formatter", END)
    workflow.add_edge("converse", END)
    workflow.add_edge("refuse", END)

    return workflow.compile()


def build_api_result_graph():
    workflow = StateGraph(QueryMindState)

    workflow.add_node("result_formatter", result_formatter)

    workflow.add_edge(START, "result_formatter")
    workflow.add_edge("result_formatter", END)

    return workflow.compile()
