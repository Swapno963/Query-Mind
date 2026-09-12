from django.test import SimpleTestCase

from agent.graph import (
    route_after_on_premise_error_analysis,
    route_after_on_premise_execution,
    route_after_on_premise_validation,
)
from agent.state import QueryMindState
from connections.services.schema_discovery import filter_schema_to_tables
from connections.services.sql_validation import ReadOnlySQLExecutor
from connections.services.workspace import explain_connection_error


class AllowListValidationTests(SimpleTestCase):
    def test_rejects_sql_without_allow_list(self):
        executor = ReadOnlySQLExecutor(allowed_tables=None)
        with self.assertRaises(PermissionError):
            executor.validate("SELECT id FROM orders")

    def test_rejects_tables_outside_allow_list(self):
        executor = ReadOnlySQLExecutor(allowed_tables={"orders", "products"})
        with self.assertRaises(PermissionError):
            executor.validate("SELECT email FROM staff")

    def test_allows_select_on_permitted_tables(self):
        executor = ReadOnlySQLExecutor(allowed_tables={"orders", "products"})
        expression = executor.validate(
            "SELECT id, total_amount FROM orders WHERE payment_status = 'PAID'"
        )
        self.assertIsNotNone(expression)

    def test_rejects_non_select(self):
        executor = ReadOnlySQLExecutor(allowed_tables={"orders"})
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

    def test_valid_sql_executes(self):
        state = self._state(validation_result={"valid": True})
        self.assertEqual(route_after_on_premise_validation(state), "execute")

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
