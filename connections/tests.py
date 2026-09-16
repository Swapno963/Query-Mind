from django.test import SimpleTestCase

from agent.graph import (
    route_after_explain,
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

    def test_rejects_select_star(self):
        executor = ReadOnlySQLExecutor(
            allowed_tables={"orders"},
            allowed_columns={"orders": ["id"]},
        )
        with self.assertRaises(PermissionError):
            executor.validate("SELECT * FROM orders")

    def test_allows_count_star(self):
        executor = ReadOnlySQLExecutor(
            allowed_tables={"orders"},
            allowed_columns={"orders": ["id"]},
        )
        self.assertIsNotNone(executor.validate("SELECT COUNT(*) AS n FROM orders"))

    def test_rejects_non_select(self):
        executor = ReadOnlySQLExecutor(
            allowed_tables={"orders"},
            allowed_columns={"orders": ["id"]},
        )
        with self.assertRaises(ValueError):
            executor.validate("DELETE FROM orders")


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
