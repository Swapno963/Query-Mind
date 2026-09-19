from django.test import SimpleTestCase
from unittest.mock import patch

from agent.graph import (
    route_after_capability,
    route_after_explain,
    route_after_mcp_execute,
    route_after_on_premise_critic,
    route_after_on_premise_error_analysis,
    route_after_on_premise_execution,
    route_after_on_premise_validation,
    route_after_planner,
)
from agent.state import QueryMindState
from connections.services.catalog import (
    catalog_from_discovery_rows,
    intersect_allow_lists,
)
from connections.services.schema_discovery import filter_schema_to_tables
from agent.intent import bind_intent_to_allow_list, rule_based_intent
from connections.services.sql_critic import critique_sql
from connections.services.sql_validation import ReadOnlySQLExecutor
from connections.services.workspace import explain_connection_error


ORDERS_COLUMNS = {"orders": ["id", "total_amount", "payment_status"]}


class AllowListValidationTests(SimpleTestCase):
    def test_rejects_sql_without_allow_list(self):
        executor = ReadOnlySQLExecutor(allowed_tables=None)
        with self.assertRaises(PermissionError):
            executor.validate("SELECT id FROM orders")

    def test_rejects_tables_outside_allow_list(self):
        executor = ReadOnlySQLExecutor(
            allowed_tables={"orders", "products"},
            allowed_columns={
                "orders": ["id"],
                "products": ["id"],
            },
        )
        with self.assertRaises(PermissionError):
            executor.validate("SELECT email FROM staff")

    def test_allows_select_on_permitted_tables(self):
        executor = ReadOnlySQLExecutor(
            allowed_tables={"orders", "products"},
            allowed_columns=ORDERS_COLUMNS | {"products": ["id"]},
        )
        expression = executor.validate(
            "SELECT id, total_amount FROM orders WHERE payment_status = 'PAID'"
        )
        self.assertIsNotNone(expression)

    def test_rejects_forbidden_column_on_allowed_table(self):
        executor = ReadOnlySQLExecutor(
            allowed_tables={"orders"},
            allowed_columns={"orders": ["id", "status"]},
        )
        with self.assertRaises(PermissionError):
            executor.validate("SELECT email FROM orders")

    def test_expands_select_star_to_allowed_columns(self):
        executor = ReadOnlySQLExecutor(
            allowed_tables={"orders"},
            allowed_columns={"orders": ["id", "total_amount", "payment_status"]},
        )
        sql = executor.normalized_sql("SELECT * FROM orders")
        self.assertNotIn("*", sql)
        self.assertIn("id", sql.lower())
        self.assertIn("total_amount", sql.lower())
        self.assertIn("payment_status", sql.lower())
        self.assertRegex(sql.lower(), r"\blimit\s+100\b")

    def test_expands_select_star_when_only_some_columns_are_allowed(self):
        executor = ReadOnlySQLExecutor(
            allowed_tables={"orders"},
            allowed_columns={"orders": ["id"]},
        )
        sql = executor.normalized_sql("SELECT * FROM orders")
        self.assertEqual(sql, "SELECT id FROM orders LIMIT 100")

    def test_expands_qualified_star(self):
        executor = ReadOnlySQLExecutor(
            allowed_tables={"orders"},
            allowed_columns={"orders": ["id", "total_amount"]},
        )
        sql = executor.normalized_sql("SELECT o.* FROM orders o")
        self.assertNotIn("*", sql)
        self.assertIn("o.id", sql.lower())
        self.assertIn("o.total_amount", sql.lower())
        self.assertRegex(sql.lower(), r"\blimit\s+100\b")

    def test_rejects_star_when_starred_table_has_no_allowed_columns(self):
        executor = ReadOnlySQLExecutor(
            allowed_tables={"orders", "customers"},
            allowed_columns={"orders": ["id"], "customers": []},
        )
        with self.assertRaises(PermissionError):
            executor.validate(
                "SELECT * FROM orders o JOIN customers c ON c.id = o.customer_id"
            )

    def test_allows_count_star(self):
        executor = ReadOnlySQLExecutor(
            allowed_tables={"orders"},
            allowed_columns={"orders": ["id"]},
        )
        sql = executor.normalized_sql("SELECT COUNT(*) AS n FROM orders")
        self.assertIn("COUNT(*)", sql.upper().replace(" ", ""))
        self.assertNotRegex(sql.lower(), r"\blimit\b")

    def test_caps_sql_limit_at_100(self):
        executor = ReadOnlySQLExecutor(
            allowed_tables={"orders"},
            allowed_columns={"orders": ["id"]},
        )
        sql = executor.normalized_sql("SELECT id FROM orders LIMIT 500")
        self.assertRegex(sql.lower(), r"\blimit\s+100\b")

    def test_keeps_sql_limit_below_100(self):
        executor = ReadOnlySQLExecutor(
            allowed_tables={"orders"},
            allowed_columns={"orders": ["id"]},
        )
        sql = executor.normalized_sql("SELECT id FROM orders LIMIT 20")
        self.assertRegex(sql.lower(), r"\blimit\s+20\b")

    def test_uses_requested_limit_and_caps_at_100(self):
        executor = ReadOnlySQLExecutor(
            allowed_tables={"orders"},
            allowed_columns={"orders": ["id"]},
        )
        sql = executor.normalized_sql(
            "SELECT * FROM orders", requested_limit=20
        )
        self.assertEqual(sql, "SELECT id FROM orders LIMIT 20")
        sql = executor.normalized_sql(
            "SELECT * FROM orders", requested_limit=1000
        )
        self.assertEqual(sql, "SELECT id FROM orders LIMIT 100")

    def test_expands_join_star_per_table(self):
        executor = ReadOnlySQLExecutor(
            allowed_tables={"orders", "customers"},
            allowed_columns={
                "orders": ["id", "customer_id"],
                "customers": ["id", "email"],
            },
        )
        sql = executor.normalized_sql(
            "SELECT * FROM orders o JOIN customers c ON c.id = o.customer_id"
        )
        lower = sql.lower()
        self.assertNotIn("*", sql)
        self.assertIn("o.id", lower)
        self.assertIn("c.email", lower)
        self.assertRegex(lower, r"\blimit\s+100\b")

    def test_rejects_non_select(self):
        executor = ReadOnlySQLExecutor(
            allowed_tables={"orders"},
            allowed_columns={"orders": ["id"]},
        )
        with self.assertRaises(ValueError):
            executor.validate("DELETE FROM orders")

    def test_rejects_insert_update_and_ddl(self):
        executor = ReadOnlySQLExecutor(
            allowed_tables={"orders"},
            allowed_columns={"orders": ["id"]},
        )
        for sql in (
            "INSERT INTO orders (id) VALUES (1)",
            "UPDATE orders SET id = 1",
            "DROP TABLE orders",
        ):
            with self.subTest(sql=sql):
                with self.assertRaises(ValueError):
                    executor.validate(sql)


class SqlRewriteNodeTests(SimpleTestCase):
    def test_sql_validator_rewrites_star_and_adds_limit(self):
        from agent.nodes.sql_validator import sql_validator

        state = QueryMindState(
            question="Show me orders",
            conversation_id=1,
            message_id=1,
            connection_id=1,
            sql="SELECT * FROM orders",
            allowed_tables=["orders"],
            allowed_columns={"orders": ["id", "total_amount"]},
        )
        result = sql_validator(state)
        self.assertTrue(result["is_valid"])
        self.assertEqual(
            result["sql"], "SELECT id, total_amount FROM orders LIMIT 100"
        )

    def test_sql_validator_uses_first_n_from_the_question(self):
        from agent.nodes.sql_validator import sql_validator

        state = QueryMindState(
            question="Show the first 12 orders",
            conversation_id=1,
            message_id=1,
            connection_id=1,
            sql="SELECT * FROM orders",
            allowed_tables=["orders"],
            allowed_columns={"orders": ["id"]},
        )
        result = sql_validator(state)
        self.assertTrue(result["is_valid"])
        self.assertEqual(result["sql"], "SELECT id FROM orders LIMIT 12")


class SchemaFilterTests(SimpleTestCase):
    def test_drops_excluded_tables(self):
        schema = """
DATABASE: PostgreSQL

TABLE: orders
Description: Orders

Columns:
- id INTEGER

TABLE: staff
Description: Staff

Columns:
- id INTEGER

RELATIONSHIPS:

- orders.user_id → staff.id
"""
        filtered = filter_schema_to_tables(schema, ["orders"])
        self.assertIn("TABLE: orders", filtered)
        self.assertNotIn("TABLE: staff", filtered)
        self.assertNotIn("staff.id", filtered)

    def test_empty_allow_list_returns_empty_schema(self):
        self.assertEqual(filter_schema_to_tables("TABLE: orders", []), "")

    def test_drops_excluded_columns(self):
        schema = """
DATABASE: PostgreSQL

TABLE: orders
Description: Orders

Columns:
- id INTEGER
- email TEXT
- total_amount NUMERIC

RELATIONSHIPS:

- orders.user_id → staff.id
"""
        filtered = filter_schema_to_tables(
            schema,
            ["orders"],
            {"orders": ["id", "total_amount"]},
        )
        self.assertIn("- id INTEGER", filtered)
        self.assertIn("total_amount", filtered)
        self.assertNotIn("email", filtered)
        self.assertNotIn("staff.id", filtered)

    def test_keeps_values_for_allowed_columns(self):
        schema = """
DATABASE: PostgreSQL

TABLE: orders
Description: Orders
Grain: one row per id

Columns:
- id INTEGER
- payment_status VARCHAR
  Values: UNPAID, PAID, REFUNDED
- secret TEXT

BUSINESS DEFINITIONS:

- "paid" means orders.payment_status = 'PAID'
- "staff" means staff.role = 'admin'
"""
        filtered = filter_schema_to_tables(
            schema,
            ["orders"],
            {"orders": ["id", "payment_status"]},
        )
        self.assertIn("Values: UNPAID, PAID, REFUNDED", filtered)
        self.assertIn("Grain: one row per id", filtered)
        self.assertIn("payment_status = 'PAID'", filtered)
        self.assertNotIn("secret", filtered)
        self.assertNotIn("staff.role", filtered)


class CatalogIngestTests(SimpleTestCase):
    def test_catalog_from_information_schema_rows(self):
        catalog = catalog_from_discovery_rows(
            [
                {
                    "table_name": "orders",
                    "column_name": "id",
                },
                {
                    "table_name": "orders",
                    "column_name": "status",
                },
                {
                    "table_name": "products",
                    "column_name": "name",
                },
            ]
        )
        self.assertEqual(catalog["tables"], ["orders", "products"])
        self.assertEqual(catalog["columns"]["orders"], ["id", "status"])

    def test_intersect_ignores_invented_names(self):
        tables, columns = intersect_allow_lists(
            requested_tables=["orders", "secrets"],
            requested_columns={
                "orders": ["id", "ssn"],
                "secrets": ["token"],
            },
            discovered_tables=["orders", "products"],
            discovered_columns={
                "orders": ["id", "status"],
                "products": ["name"],
            },
        )
        self.assertEqual(tables, ["orders"])
        self.assertEqual(columns, {"orders": ["id"]})

    def test_intersect_requires_at_least_one_column(self):
        tables, columns = intersect_allow_lists(
            requested_tables=["orders"],
            requested_columns={"orders": []},
            discovered_tables=["orders"],
            discovered_columns={"orders": ["id"]},
        )
        self.assertEqual(tables, [])
        self.assertEqual(columns, {})


class GraphFailClosedTests(SimpleTestCase):
    def _state(self, **kwargs):
        data = dict(
            question="q",
            conversation_id=1,
            message_id=1,
            connection_id=1,
        )
        data.update(kwargs)
        return QueryMindState(**data)

    def test_invalid_sql_does_not_execute_when_fail_closed(self):
        state = self._state(
            validation_result={"valid": False, "fail_closed": True, "kind": "unavailable"}
        )
        self.assertEqual(route_after_on_premise_validation(state), "refuse")

    def test_valid_sql_goes_to_explain(self):
        state = self._state(validation_result={"valid": True})
        self.assertEqual(route_after_on_premise_validation(state), "explain")

    def test_explain_ok_goes_to_critic(self):
        state = self._state(explain_result={"ok": True})
        self.assertEqual(route_after_explain(state), "critic")

    def test_critic_ok_goes_to_execute(self):
        state = self._state(critic_result={"ok": True})
        self.assertEqual(route_after_on_premise_critic(state), "execute")

    def test_invalid_intent_refuses(self):
        state = self._state(intent={"valid": False}, status="failed")
        self.assertEqual(route_after_planner(state), "refuse")

    def test_zero_rows_are_success_path(self):
        state = self._state(
            execution_result={"success": True, "row_count": 0, "kind": "zero_rows"}
        )
        self.assertEqual(route_after_on_premise_execution(state), "success")

    def test_unavailable_execution_does_not_repair(self):
        state = self._state(
            execution_result={"success": False, "kind": "unavailable"},
            answer_kind="unavailable",
        )
        self.assertEqual(route_after_on_premise_execution(state), "refuse")

    def test_error_analysis_can_repair(self):
        state = self._state(error_analysis={"action": "repair"}, retry_count=0)
        self.assertEqual(route_after_on_premise_error_analysis(state), "repair")

    def test_error_analysis_stops_after_retry_budget(self):
        state = self._state(
            error_analysis={"action": "schema"},
            retry_count=3,
            sql_attempts=3,
        )
        self.assertEqual(route_after_on_premise_error_analysis(state), "end")

    def test_schema_refresh_is_not_repeated(self):
        from agent.nodes.error_analyzer import error_analyzer

        first = error_analyzer(
            self._state(database_error='column "foo" does not exist')
        )
        self.assertEqual(first["error_analysis"]["action"], "schema")
        self.assertEqual(first["retry_count"], 1)
        second = error_analyzer(
            self._state(
                database_error='column "foo" does not exist',
                error_analysis=first["error_analysis"],
                retry_count=first["retry_count"],
                sql_attempts=1,
            )
        )
        self.assertEqual(second["error_analysis"]["action"], "repair")
        self.assertEqual(
            route_after_on_premise_error_analysis(
                self._state(
                    error_analysis=second["error_analysis"],
                    retry_count=second["retry_count"],
                    sql_attempts=1,
                )
            ),
            "repair",
        )


class ResultFormatterTests(SimpleTestCase):
    def test_show_all_orders_does_not_call_llm(self):
        from agent.nodes.result_formatter import result_formatter

        state = QueryMindState(
            question="show all orders",
            conversation_id=1,
            message_id=1,
            connection_id=1,
            intent={
                "valid": True,
                "output": "row_list",
                "tables": ["orders"],
                "entity": "orders",
            },
            execution_result={
                "success": True,
                "kind": "success",
                "rows": [{"id": 1, "status": "paid"}, {"id": 2, "status": "pending"}],
            },
        )
        with patch("agent.nodes.result_formatter.ask_state") as ask:
            result = result_formatter(state)
        ask.assert_not_called()
        self.assertIn("2 matching rows", result["final_answer"])
        self.assertEqual(result["status"], "completed")


class ConnectionErrorCopyTests(SimpleTestCase):
    def test_auth_failure_is_plain_language(self):
        self.assertIn(
            "username and password",
            explain_connection_error(Exception("password authentication failed")),
        )

    def test_network_failure_is_plain_language(self):
        self.assertIn("host", explain_connection_error(Exception("connection refused")))


RELATIONSHIPS = [
    {
        "source_table": "order_items",
        "source_column": "order_id",
        "target_table": "orders",
        "target_column": "id",
    }
]


class SqlCriticTests(SimpleTestCase):
    def test_fan_out_sum_is_rejected(self):
        result = critique_sql(
            "SELECT SUM(orders.total_amount) FROM orders JOIN order_items ON order_items.order_id = orders.id",
            intent={"tables": ["orders"], "entity": "orders", "metric": {"expr": "SUM(orders.total_amount)"}},
            relationships=RELATIONSHIPS,
            allowed_tables=["orders", "order_items"],
        )
        self.assertFalse(result["ok"])
        self.assertIn("fan_out_on_sum", result["issues"])

    def test_order_only_sum_is_ok(self):
        result = critique_sql(
            "SELECT SUM(orders.total_amount) FROM orders WHERE orders.payment_status = 'PAID'",
            intent={"tables": ["orders"], "entity": "orders", "metric": {"expr": "SUM(orders.total_amount)"}},
            relationships=RELATIONSHIPS,
            allowed_tables=["orders", "order_items"],
        )
        self.assertTrue(result["ok"])

    def test_exists_avoids_fan_out(self):
        result = critique_sql(
            "SELECT SUM(orders.total_amount) FROM orders WHERE EXISTS (SELECT 1 FROM order_items WHERE order_items.order_id = orders.id)",
            intent={"tables": ["orders"], "entity": "orders"},
            relationships=RELATIONSHIPS,
            allowed_tables=["orders", "order_items"],
        )
        self.assertTrue(result["ok"])


class IntentBindTests(SimpleTestCase):
    def test_rejects_unknown_entity(self):
        bound = bind_intent_to_allow_list(
            {"entity": "staff", "tables": ["staff"], "output": "row_list"},
            ["orders"],
            {"orders": ["id"]},
        )
        self.assertFalse(bound["valid"])

    def test_revenue_rule_uses_orders(self):
        ir = rule_based_intent(
            "How much revenue did we make from paid orders?",
            ["orders"],
            {"orders": ["id", "total_amount", "payment_status", "ordered_at"]},
            {
                "metrics": {
                    "revenue": {
                        "expr": "SUM(orders.total_amount)",
                        "table": "orders",
                        "grain": "order",
                        "filters": [{"column": "orders.payment_status", "op": "eq", "value": "PAID"}],
                    }
                },
                "aliases": {"paid": {"column": "orders.payment_status", "value": "PAID"}},
            },
        )
        self.assertTrue(ir["valid"])
        self.assertEqual(ir["entity"], "orders")
        self.assertEqual(ir["grain"], "order")


class EvalMetricsTests(SimpleTestCase):
    def test_fanout_sql_fails_eval_trap(self):
        from eval.metrics import score_prediction

        case = {
            "id": "fanout_revenue_with_items",
            "category": "fan_out",
            "allowed_tables": ["orders", "order_items"],
            "allowed_columns": {
                "orders": ["id", "total_amount", "payment_status"],
                "order_items": ["id", "order_id", "unit_price", "quantity"],
            },
            "gold_tables": ["orders"],
            "gold_grain": "order",
            "must_not_join": ["order_items"],
            "must_refuse": False,
        }
        sql = (
            "SELECT SUM(orders.total_amount) FROM orders "
            "JOIN order_items ON order_items.order_id = orders.id"
        )
        scored = score_prediction(case, sql=sql, refused=False, linked_tables=["orders", "order_items"])
        self.assertFalse(scored["fan_out_ok"])


class EngineSupportTests(SimpleTestCase):
    def test_normalize_engine_aliases(self):
        from connections.services.engines import normalize_engine, sqlglot_dialect

        self.assertEqual(normalize_engine("PostgreSQL"), "postgres")
        self.assertEqual(normalize_engine("mariadb"), "mysql")
        self.assertEqual(sqlglot_dialect("mssql"), "tsql")
        with self.assertRaises(ValueError):
            normalize_engine("mongodb")

    def test_mysql_select_validates(self):
        executor = ReadOnlySQLExecutor(
            allowed_tables={"orders"},
            allowed_columns={"orders": ["id"]},
            engine="mysql",
        )
        self.assertIsNotNone(executor.validate("SELECT id FROM orders"))

    def test_oracle_and_mssql_select_validate(self):
        for engine in ("oracle", "mssql"):
            executor = ReadOnlySQLExecutor(
                allowed_tables={"orders"},
                allowed_columns={"orders": ["id"]},
                engine=engine,
            )
            self.assertIsNotNone(executor.validate("SELECT id FROM orders"))

    def test_discovery_sql_varies_by_engine(self):
        from connections.services.catalog import discovery_sql_for

        self.assertIn("DATABASE()", discovery_sql_for("mysql"))
        self.assertIn("user_tab_columns", discovery_sql_for("oracle"))
        self.assertIn("INFORMATION_SCHEMA.COLUMNS", discovery_sql_for("mssql"))


GET_ORDER = {
    "name": "get_order",
    "description": "Fetch one order by id",
    "inputSchema": {
        "type": "object",
        "properties": {"order_id": {"type": "string"}},
        "required": ["order_id"],
    },
}
UPDATE_STATUS = {
    "name": "update_order_status",
    "description": "Update an order status",
    "inputSchema": {
        "type": "object",
        "properties": {
            "order_id": {"type": "string"},
            "status": {"type": "string"},
        },
        "required": ["order_id", "status"],
    },
}
CREATE_CUSTOMER = {
    "name": "create_customer",
    "description": "Create a customer",
    "inputSchema": {
        "type": "object",
        "properties": {"name": {"type": "string"}},
    },
}
DELETE_CUSTOMER = {
    "name": "delete_customer",
    "description": "Delete a customer",
    "inputSchema": {
        "type": "object",
        "properties": {"customer_id": {"type": "string"}},
    },
}


class ExecutionPolicyTests(SimpleTestCase):
    def _state(self, **kwargs):
        data = dict(question="q", conversation_id=1, message_id=1, connection_id=1)
        data.update(kwargs)
        return QueryMindState(**data)

    def test_policy_read_allows_sql(self):
        from agent.policy import decide, resolve_mode

        self.assertTrue(decide("READ")["sql_allowed"])
        self.assertFalse(decide("UPDATE")["sql_allowed"])
        self.assertTrue(decide("UPDATE")["mcp_required"])
        self.assertFalse(decide("UPDATE", product_surface="chat")["mcp_allowed"])
        self.assertEqual(resolve_mode(operation="READ", mcp_capable=True, mcp_available=True), "mcp")
        self.assertEqual(resolve_mode(operation="READ", mcp_capable=False, mcp_available=True), "sql")
        self.assertEqual(resolve_mode(operation="CREATE", mcp_capable=True, mcp_available=True), "mcp")
        self.assertEqual(resolve_mode(operation="CREATE", mcp_capable=False, mcp_available=True), "deny")
        self.assertEqual(resolve_mode(operation="DELETE", mcp_capable=False, mcp_available=False), "deny")
        self.assertEqual(
            resolve_mode(
                operation="DELETE",
                mcp_capable=True,
                mcp_available=True,
                product_surface="chat",
            ),
            "deny",
        )

    def test_greeting_is_conversation_not_sql(self):
        from agent.graph import route_after_classify
        from agent.nodes.classify import classify_operation
        from agent.operation import classify_request_kind

        self.assertEqual(classify_request_kind("hello", use_llm=False), "conversation")
        self.assertEqual(classify_request_kind("Thanks!", use_llm=False), "conversation")
        self.assertEqual(classify_request_kind("tell me a joke", use_llm=False), "conversation")
        self.assertEqual(classify_request_kind("How many orders?", use_llm=False), "query")
        result = classify_operation(self._state(question="Thanks!"))
        self.assertEqual(result["execution_mode"], "converse")
        self.assertEqual(route_after_classify(self._state(execution_mode="converse")), "converse")
        self.assertEqual(route_after_classify(self._state(execution_mode="sql", status="running")), "policy")

    def test_chat_refuses_writes_and_does_not_ask_for_cud(self):
        from agent.nodes.classify import classify_operation
        from agent.nodes.refuse import refuse_answer

        result = classify_operation(
            self._state(question="Delete inactive customers", product_surface="chat")
        )
        self.assertEqual(result["execution_mode"], "deny")
        self.assertEqual(result["routing"]["reason"], "chat_read_only")
        refused = refuse_answer(
            self._state(
                answer_kind="unsupported_operation",
                product_surface="chat",
                routing={"reason": "chat_read_only"},
            )
        )
        self.assertNotIn("look up, create, update, or delete something", refused["final_answer"])
        self.assertIn("only look up", refused["final_answer"].lower())
        clarify = refuse_answer(self._state(answer_kind="needs_clarification"))
        self.assertNotIn("create, update, or delete something", clarify["final_answer"])

    def test_requested_result_limit_from_question_and_intent(self):
        from agent.operation import requested_result_limit, requested_result_limit_for_state

        self.assertEqual(requested_result_limit(question="Show the first 12 orders"), 12)
        self.assertEqual(requested_result_limit({"parameters": {"limit": 20}}), 20)
        self.assertEqual(requested_result_limit({"parameters": {"limit": 500}}), 500)
        self.assertIsNone(requested_result_limit(question="Show me orders"))
        state = self._state(question="top 8 products")
        self.assertEqual(requested_result_limit_for_state(state), 8)

    def test_verb_override_delete_is_not_read(self):
        from agent.operation import extract_operation

        intent = extract_operation("delete inactive customers", use_llm=False)
        self.assertEqual(intent["operation"], "DELETE")

    def test_ambiguous_request_is_not_guessed(self):
        from agent.operation import extract_operation

        intent = extract_operation("Handle this customer.", use_llm=False)
        self.assertFalse(intent["valid"])
        self.assertEqual(intent["reason"], "needs_clarification")

    def test_read_get_order_uses_mcp(self):
        from agent.nodes.capability import capability_resolve
        from agent.operation import extract_operation

        intent = extract_operation("Show me order 123", use_llm=False)
        state = self._state(operation_intent=intent, question="Show me order 123")
        result = capability_resolve(state, tools=[GET_ORDER])
        self.assertEqual(result["execution_mode"], "mcp")
        self.assertEqual(result["routing"]["tool"], "get_order")
        self.assertEqual(result["mcp_result"]["arguments"]["order_id"], "123")

    def test_read_aggregation_falls_back_to_sql(self):
        from agent.nodes.capability import capability_resolve
        from agent.operation import extract_operation

        intent = extract_operation(
            "Show me the 20 products with the highest revenue this year",
            use_llm=False,
        )
        self.assertIn("aggregation", intent["query_features"])
        state = self._state(operation_intent=intent)
        result = capability_resolve(state, tools=[GET_ORDER])
        self.assertEqual(result["execution_mode"], "sql")
        self.assertTrue(result["routing"]["sql_fallback"])

    def test_update_with_tool_uses_mcp(self):
        from agent.nodes.capability import capability_resolve
        from agent.operation import extract_operation

        intent = extract_operation("Mark order 123 as delivered", use_llm=False)
        self.assertEqual(intent["operation"], "UPDATE")
        result = capability_resolve(self._state(operation_intent=intent), tools=[UPDATE_STATUS])
        self.assertEqual(result["execution_mode"], "mcp")
        self.assertEqual(result["routing"]["tool"], "update_order_status")

    def test_update_without_tool_is_denied(self):
        from agent.nodes.capability import capability_resolve
        from agent.operation import extract_operation

        intent = extract_operation("Change the customer's credit limit", use_llm=False)
        result = capability_resolve(self._state(operation_intent=intent), tools=[GET_ORDER])
        self.assertEqual(result["execution_mode"], "deny")
        self.assertFalse(result["routing"]["sql_fallback"])

    def test_create_and_delete_routing(self):
        from agent.nodes.capability import capability_resolve
        from agent.operation import extract_operation

        created = extract_operation("Create a customer", use_llm=False)
        self.assertEqual(
            capability_resolve(self._state(operation_intent=created), tools=[CREATE_CUSTOMER])[
                "execution_mode"
            ],
            "mcp",
        )
        self.assertEqual(
            capability_resolve(self._state(operation_intent=created), tools=[GET_ORDER])[
                "execution_mode"
            ],
            "deny",
        )
        deleted = extract_operation("Remove inactive customers", use_llm=False)
        self.assertEqual(deleted["operation"], "DELETE")
        self.assertEqual(
            capability_resolve(self._state(operation_intent=deleted), tools=[DELETE_CUSTOMER])[
                "execution_mode"
            ],
            "mcp",
        )
        self.assertEqual(
            capability_resolve(self._state(operation_intent=deleted), tools=[])["execution_mode"],
            "deny",
        )

    def test_capability_route_never_sends_writes_to_sql(self):
        state = self._state(execution_mode="deny")
        self.assertEqual(route_after_capability(state), "refuse")
        state = self._state(execution_mode="sql")
        self.assertEqual(route_after_capability(state), "planner")
        state = self._state(execution_mode="mcp")
        self.assertEqual(route_after_capability(state), "mcp")

    def test_mcp_failure_does_not_route_to_sql(self):
        from agent.mcp.client import MCPClientError
        from agent.nodes.mcp_executor import mcp_execute
        from unittest.mock import patch

        state = self._state(
            execution_mode="mcp",
            mcp_server_url="https://example.com/mcp",
            mcp_result={"tool": "update_order_status", "arguments": {"order_id": "123"}},
            routing={"mode": "mcp", "tool": "update_order_status"},
        )
        with patch("agent.nodes.mcp_executor.call_tool", side_effect=MCPClientError("boom")):
            result = mcp_execute(state)
        self.assertEqual(result["answer_kind"], "mcp_failed")
        failed = self._state(
            execution_result=result["execution_result"],
            execution_mode="deny",
        )
        self.assertEqual(route_after_mcp_execute(failed), "refuse")
        self.assertNotEqual(route_after_mcp_execute(failed), "planner")

    def test_redact_hides_secrets(self):
        from agent.mcp.redact import redact

        hidden = redact({"token": "abc", "order_id": "123"})
        self.assertEqual(hidden["token"], "[redacted]")
        self.assertEqual(hidden["order_id"], "123")

    def test_missing_required_params_clarify(self):
        from agent.nodes.capability import capability_resolve

        create_item = {
            "name": "create_menu_item",
            "description": "Create a menu item",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "price": {"type": "string"},
                    "category_name": {"type": "string"},
                },
                "required": ["name", "price", "category_name"],
            },
        }
        intent = {
            "valid": True,
            "operation": "CREATE",
            "resource": "item",
            "action": "create",
            "parameters": {"name": "Chicken Biryani"},
            "query_features": [],
            "reason": "",
        }
        result = capability_resolve(self._state(operation_intent=intent), tools=[create_item])
        self.assertEqual(result["execution_mode"], "clarify")
        self.assertEqual(result["answer_kind"], "needs_parameters")
        self.assertIn("price", result["routing"]["missing"])

    def test_mcp_only_read_does_not_fallback_to_sql(self):
        from agent.nodes.capability import capability_resolve
        from agent.operation import extract_operation
        from agent.policy import resolve_mode

        self.assertEqual(
            resolve_mode(
                operation="READ",
                mcp_capable=False,
                mcp_available=True,
                sql_available=False,
            ),
            "deny",
        )
        intent = extract_operation("Show me order 123", use_llm=False)
        result = capability_resolve(
            self._state(
                operation_intent=intent,
                question="Show me order 123",
                mcp_server_url="https://example.com/mcp",
            ),
            tools=[],
        )
        self.assertEqual(result["execution_mode"], "deny")
        self.assertFalse(result["routing"]["sql_fallback"])

    def test_create_category_matches_menu_tool(self):
        from agent.nodes.capability import capability_resolve
        from agent.operation import extract_operation

        create_category = {
            "name": "create_menu_category",
            "description": "Create a menu category",
            "inputSchema": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        }
        intent = extract_operation("Create a new category called Desserts", use_llm=False)
        intent["parameters"] = {"name": "Desserts"}
        result = capability_resolve(self._state(operation_intent=intent), tools=[create_category])
        self.assertEqual(result["execution_mode"], "mcp")
        self.assertEqual(result["routing"]["tool"], "create_menu_category")

    def test_extract_operation_falls_back_when_llm_unavailable(self):
        from unittest.mock import patch

        from agent.operation import extract_operation
        from chat.api.chat_service import LLMUnavailable

        with patch("agent.operation.ask_llm", side_effect=LLMUnavailable("down")):
            intent = extract_operation("Show today's orders", use_llm=True)
        self.assertTrue(intent["valid"])
        self.assertEqual(intent["operation"], "READ")

    def test_list_tools_forwards_auth_headers(self):
        from unittest.mock import patch

        from agent.nodes.capability import capability_resolve
        from agent.operation import extract_operation

        intent = extract_operation("Show me order 123", use_llm=False)
        state = self._state(
            operation_intent=intent,
            question="Show me order 123",
            mcp_server_url="https://example.com/mcp",
            mcp_headers={"Authorization": "Bearer secret"},
        )
        with patch("agent.nodes.capability.list_tools", return_value=[GET_ORDER]) as listed:
            capability_resolve(state)
            listed.assert_called_with(
                "https://example.com/mcp",
                {"Authorization": "Bearer secret"},
            )


class JsonSafeValueTests(SimpleTestCase):
    def test_decimal_becomes_string(self):
        from decimal import Decimal

        from connections.services.jsonutil import json_safe_row

        row = json_safe_row({"average_price": Decimal("19.9900")})
        self.assertEqual(row["average_price"], "19.9900")
        self.assertIsInstance(row["average_price"], str)
