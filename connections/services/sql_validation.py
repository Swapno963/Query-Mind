from __future__ import annotations

from typing import Any

import sqlglot
from sqlglot import exp

from django.db import connections, transaction


class ReadOnlySQLExecutor:
    """
    Safely validates and executes LLM-generated PostgreSQL SELECT queries.

    Pipeline:

        SQL
         ↓
        Parse
         ↓
        Validate
         ↓
        Permission check
         ↓
        Read-only transaction
         ↓
        Statement timeout
         ↓
        Execute
         ↓
        Stream rows
    """

    def __init__(
        self,
        database: str = "client",
        allowed_tables: set[str] | None = None,
        statement_timeout_ms: int = 10_000,
        max_rows: int = 10_000,
        fetch_size: int = 500,
    ):
        self.database = database
        self.allowed_tables = allowed_tables
        self.statement_timeout_ms = statement_timeout_ms
        self.max_rows = max_rows
        self.fetch_size = fetch_size

    def validate(self, sql: str) -> exp.Expression:
        """
        Parse and validate SQL without executing it.
        """

        sql = sql.strip()

        if not sql:
            raise ValueError("SQL query is empty.")

        # Reject multiple SQL statements.
        statements = sqlglot.parse(sql, dialect="postgres")

        if len(statements) != 1:
            raise ValueError("Only one SQL statement is allowed.")

        expression = statements[0]

        # Only SELECT statements.
        if not isinstance(expression, exp.Select):
            raise ValueError(
                f"Only SELECT queries are allowed. " f"Received: {expression.key}"
            )

        # self._validate_tables(expression)

        return expression

    def _validate_tables(self, expression: exp.Expression) -> None:
        """
        Optional table-level authorization.
        """

        if self.allowed_tables is None:
            return

        tables = {table.name for table in expression.find_all(exp.Table)}

        unauthorized = tables - self.allowed_tables

        if unauthorized:
            raise PermissionError(
                f"Access to these tables is not allowed: "
                f"{', '.join(sorted(unauthorized))}"
            )

    def execute(self, sql: str) -> list[dict[str, Any]]:
        """
        Execute query and return all rows.

        Use stream() instead when result sets can be large.
        """

        expression = self.validate(sql)

        # Generate normalized SQL from the AST.
        safe_sql = expression.sql(dialect="postgres")

        connection = connections[self.database]

        with transaction.atomic(using=self.database):

            with connection.cursor() as cursor:

                # Make the transaction read-only.
                cursor.execute("SET TRANSACTION READ ONLY")

                # Prevent queries from running indefinitely.
                cursor.execute(
                    "SET LOCAL statement_timeout = %s",
                    [self.statement_timeout_ms],
                )

                cursor.execute(safe_sql)

                columns = [column[0] for column in cursor.description]

                rows = cursor.fetchmany(self.max_rows)

                return [dict(zip(columns, row)) for row in rows]

    def stream(self, sql: str):
        expression = self.validate(sql)

        safe_sql = expression.sql(dialect="postgres")

        connection = connections[self.database]

        total_rows = 0

        with transaction.atomic(using=self.database):

            # IMPORTANT:
            # Use a normal cursor for transaction configuration.
            with connection.cursor() as cursor:

                cursor.execute("SET TRANSACTION READ ONLY")

                cursor.execute(
                    "SET LOCAL statement_timeout = %s",
                    [self.statement_timeout_ms],
                )

            # Now create the server-side/chunked cursor.
            with connection.chunked_cursor() as cursor:

                cursor.execute(safe_sql)

                columns = [column[0] for column in cursor.description]

                while True:

                    rows = cursor.fetchmany(self.fetch_size)

                    if not rows:
                        break

                    for row in rows:

                        total_rows += 1

                        if total_rows > self.max_rows:
                            return

                        yield dict(zip(columns, row))

    # def stream(
    #     self,
    #     sql: str,
    # ) -> Generator[dict[str, Any], None, None]:
    #     """
    #     Stream query results in batches.

    #     The SQL is completely generated and validated before
    #     execution starts.
    #     """

    #     expression = self.validate(sql)

    #     safe_sql = expression.sql(dialect="postgres")

    #     connection = connections[self.database]

    #     total_rows = 0

    #     with transaction.atomic(using=self.database):

    #         # Django's PostgreSQL backend provides a chunked cursor
    #         # that is suitable for large result sets.
    #         with connection.chunked_cursor() as cursor:

    #             cursor.execute("SET TRANSACTION READ ONLY")

    #             cursor.execute(
    #                 "SET LOCAL statement_timeout = %s",
    #                 [self.statement_timeout_ms],
    #             )

    #             cursor.execute(safe_sql)

    #             columns = [column[0] for column in cursor.description]

    #             while True:

    #                 rows = cursor.fetchmany(self.fetch_size)

    #                 if not rows:
    #                     break

    #                 for row in rows:

    #                     total_rows += 1

    #                     if total_rows > self.max_rows:
    #                         return

    #                     yield dict(zip(columns, row))
