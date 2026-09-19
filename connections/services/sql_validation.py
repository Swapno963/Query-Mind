from __future__ import annotations

from typing import Any, Iterator

import sqlglot
from sqlglot import exp

from django.db import connections, transaction

from connections.services.engines import (
    ENGINE_MYSQL,
    ENGINE_MSSQL,
    ENGINE_ORACLE,
    ENGINE_POSTGRES,
    normalize_engine,
    sqlglot_dialect,
)
from connections.services.jsonutil import json_safe_row

DEFAULT_RESULT_LIMIT = 100


def cap_result_limit(
    requested_limit: int | None, maximum: int = DEFAULT_RESULT_LIMIT
) -> int:
    try:
        n = int(requested_limit) if requested_limit is not None else maximum
    except (TypeError, ValueError):
        n = maximum
    if n < 1:
        n = maximum
    return min(n, maximum)


class ReadOnlySQLExecutor:
    """
    Validate and execute LLM-generated SELECT queries.

    PostgreSQL uses Django's database wrapper. MySQL, Oracle, and SQL Server
    execute through their native drivers when a workspace is provided.
    """

    def __init__(
        self,
        database: str = "client",
        allowed_tables: set[str] | None = None,
        allowed_columns: dict[str, set[str] | list[str]] | None = None,
        statement_timeout_ms: int = 10_000,
        max_rows: int | None = None,
        fetch_size: int = 500,
        engine: str = ENGINE_POSTGRES,
        workspace=None,
    ):
        if workspace is not None:
            engine = getattr(workspace, "engine", engine)
        self.workspace = workspace
        self.database = database
        self.engine = normalize_engine(engine)
        self.dialect = sqlglot_dialect(self.engine)
        self.allowed_tables = allowed_tables
        self.allowed_column_order = {
            str(table).lower(): list(
                dict.fromkeys(str(col).lower() for col in (cols or []))
            )
            for table, cols in (allowed_columns or {}).items()
        }
        self.allowed_columns = {
            table: set(cols) for table, cols in self.allowed_column_order.items()
        }
        self.statement_timeout_ms = statement_timeout_ms
        self.max_rows = DEFAULT_RESULT_LIMIT if max_rows is None else max_rows
        self.fetch_size = fetch_size

    def normalized_sql(self, sql: str, requested_limit: int | None = None) -> str:
        return self.validate(sql, requested_limit=requested_limit).sql(
            dialect=self.dialect
        )

    def uses_django_connection(self) -> bool:
        return self.engine == ENGINE_POSTGRES and not self._driver_workspace()

    def _driver_workspace(self):
        if self.workspace is None:
            return None
        if self.engine == ENGINE_POSTGRES:
            return None
        return self.workspace

    def explain(self, sql: str, requested_limit: int | None = None) -> dict[str, Any]:
        expression = self.validate(sql, requested_limit=requested_limit)
        safe_sql = expression.sql(dialect=self.dialect)
        if self.engine in {ENGINE_ORACLE, ENGINE_MSSQL}:
            return {
                "ok": True,
                "skipped": True,
                "sql": safe_sql,
                "reason": "EXPLAIN JSON is not implemented for this engine.",
            }
        if self._driver_workspace() is not None:
            return self._explain_driver(safe_sql)
        connection = connections[self.database]
        with transaction.atomic(using=self.database):
            with connection.cursor() as cursor:
                self._apply_read_only(cursor)
                if self.engine == ENGINE_POSTGRES:
                    cursor.execute(f"EXPLAIN (FORMAT JSON) {safe_sql}")
                    row = cursor.fetchone()
                    return {"ok": True, "plan": row[0] if row else None, "sql": safe_sql}
                if self.engine == ENGINE_MYSQL:
                    cursor.execute(f"EXPLAIN FORMAT=JSON {safe_sql}")
                    row = cursor.fetchone()
                    return {"ok": True, "plan": row[0] if row else None, "sql": safe_sql}
                return {
                    "ok": True,
                    "skipped": True,
                    "sql": safe_sql,
                    "reason": "EXPLAIN is not implemented for this engine.",
                }

    def validate(
        self, sql: str, requested_limit: int | None = None
    ) -> exp.Expression:
        sql = sql.strip()
        if not sql:
            raise ValueError("SQL query is empty.")
        statements = sqlglot.parse(sql, dialect=self.dialect)
        if len(statements) != 1:
            raise ValueError("Only one SQL statement is allowed.")
        expression = statements[0]
        if not isinstance(expression, exp.Select):
            raise ValueError(
                f"Only SELECT queries are allowed. Received: {expression.key}"
            )
        self._validate_tables(expression)
        for select in reversed(list(expression.find_all(exp.Select))):
            self._expand_select_stars(select)
        self._validate_columns(expression)
        self._apply_result_limit(expression, requested_limit)
        return expression

    def _validate_tables(self, expression: exp.Expression) -> None:
        if not self.allowed_tables:
            raise PermissionError(
                "No allowed tables. QueryMind will not run this query."
            )
        allowed = {str(name).lower() for name in self.allowed_tables}
        cte_names = {
            str(cte.alias_or_name).lower() for cte in expression.find_all(exp.CTE)
        }
        tables = {
            str(table.name).lower()
            for table in expression.find_all(exp.Table)
            if table.name
        }
        tables -= cte_names
        unauthorized = tables - allowed
        if unauthorized:
            raise PermissionError(
                "Access to these tables is not allowed: "
                f"{', '.join(sorted(unauthorized))}"
            )

    def _validate_columns(self, expression: exp.Expression) -> None:
        if not self.allowed_columns:
            raise PermissionError(
                "No allowed columns. QueryMind will not run this query."
            )
        for column in expression.find_all(exp.Column):
            name = str(column.name or "").lower()
            if not name or name == "*":
                raise PermissionError(
                    "SELECT * is not allowed. Name only the columns QueryMind may use."
                )
            table = str(column.table or "").lower()
            if table:
                real = self._resolve_table_name(expression, table)
                allowed = self.allowed_columns.get(real) or self.allowed_columns.get(
                    table
                )
                if allowed is None or name not in allowed:
                    raise PermissionError(
                        f"Access to {table}.{name} is not allowed."
                    )
                continue
            matches = [
                tbl
                for tbl, cols in self.allowed_columns.items()
                if name in cols
            ]
            if not matches:
                raise PermissionError(
                    f"Access to column {name} is not allowed."
                )

    def _expand_select_stars(self, select: exp.Select) -> None:
        new_exprs: list[exp.Expression] = []
        changed = False
        for item in select.expressions:
            if self._is_countable_star(item):
                new_exprs.append(item)
                continue
            tables = self._tables_for_star(item, select)
            if tables is None:
                new_exprs.append(item)
                continue
            if not tables:
                raise PermissionError(
                    "SELECT * is not allowed. Name only the columns QueryMind may use."
                )
            changed = True
            qualify_all = len(tables) > 1
            for qualifier, real_name in tables:
                cols = self.allowed_column_order.get(real_name) or []
                if not cols:
                    raise PermissionError(
                        f"Access to {real_name}.* is not allowed."
                    )
                table_arg = None
                if qualifier and (qualify_all or qualifier != real_name):
                    table_arg = qualifier
                for col in cols:
                    if table_arg:
                        new_exprs.append(exp.column(col, table=table_arg))
                    else:
                        new_exprs.append(exp.column(col))
        if changed:
            select.set("expressions", new_exprs)

    def _is_countable_star(self, item: exp.Expression) -> bool:
        stars = list(item.find_all(exp.Star))
        if not stars:
            return False
        return all(self._is_aggregate_star(star) for star in stars)

    def _is_aggregate_star(self, star: exp.Star) -> bool:
        parent = star.parent
        while parent is not None:
            if isinstance(parent, (exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max)):
                return True
            if isinstance(parent, exp.Select):
                return False
            parent = parent.parent
        return False

    def _tables_for_star(
        self, item: exp.Expression, select: exp.Select
    ) -> list[tuple[str, str]] | None:
        stars = [star for star in item.find_all(exp.Star) if not self._is_aggregate_star(star)]
        if not stars:
            return None
        qualifier = ""
        if isinstance(item, exp.Column):
            qualifier = str(item.table or "").lower()
        elif isinstance(item, exp.Star):
            qualifier = str(item.args.get("table") or "").lower()
        scoped = self._scope_tables(select)
        if qualifier:
            real = self._resolve_table_name(select, qualifier)
            return [(qualifier, real)]
        return scoped

    def _direct_from_sources(self, select: exp.Select) -> list[exp.Expression]:
        sources: list[exp.Expression] = []
        from_clause = select.args.get("from_")
        if from_clause is not None and from_clause.this is not None:
            sources.append(from_clause.this)
        for join in select.args.get("joins") or []:
            if join.this is not None:
                sources.append(join.this)
        return sources

    def _scope_tables(self, select: exp.Select) -> list[tuple[str, str]]:
        tables: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for source in self._direct_from_sources(select):
            if not isinstance(source, exp.Table):
                continue
            real = str(source.name or "").lower()
            if not real:
                continue
            alias = str(source.alias_or_name or real).lower()
            key = (alias, real)
            if key in seen:
                continue
            seen.add(key)
            tables.append((alias, real))
        return tables

    def _resolve_table_name(self, expression: exp.Expression, name: str) -> str:
        wanted = (name or "").lower()
        if not wanted:
            return wanted
        for select in expression.find_all(exp.Select):
            for alias, real in self._scope_tables(select):
                if wanted in {alias, real}:
                    return real
        return wanted

    def _existing_limit(self, expression: exp.Select) -> int | None:
        limit = expression.args.get("limit")
        if limit is None:
            return None
        if isinstance(limit, exp.Fetch):
            lit = limit.args.get("count") or limit.args.get("this")
        else:
            lit = limit.args.get("expression") or limit.args.get("this")
        if lit is None:
            return None
        raw = getattr(lit, "this", lit)
        try:
            return int(str(raw))
        except (TypeError, ValueError):
            return None

    def _is_scalar_aggregate(self, expression: exp.Select) -> bool:
        if expression.args.get("group") is not None:
            return False
        exprs = list(expression.expressions or [])
        if not exprs:
            return False
        return all(bool(item.find(exp.AggFunc)) for item in exprs)

    def _apply_result_limit(
        self, expression: exp.Select, requested_limit: int | None
    ) -> None:
        existing = self._existing_limit(expression)
        if existing is None and self._is_scalar_aggregate(expression):
            return
        cap = cap_result_limit(requested_limit)
        if existing is not None:
            cap = min(existing, cap)
        expression.limit(cap, copy=False)

    def _apply_read_only(self, cursor) -> None:
        try:
            if self.engine == ENGINE_POSTGRES:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(
                    "SET LOCAL statement_timeout = %s",
                    [self.statement_timeout_ms],
                )
                return
            if self.engine == ENGINE_MYSQL:
                cursor.execute("START TRANSACTION READ ONLY")
                try:
                    cursor.execute(
                        "SET SESSION MAX_EXECUTION_TIME = %s",
                        [self.statement_timeout_ms],
                    )
                except Exception:
                    pass
                return
            if self.engine == ENGINE_ORACLE:
                cursor.execute("SET TRANSACTION READ ONLY")
                return
            if self.engine == ENGINE_MSSQL:
                cursor.execute(f"SET LOCK_TIMEOUT {int(self.statement_timeout_ms)}")
        except Exception:
            pass

    def execute(
        self, sql: str, requested_limit: int | None = None
    ) -> list[dict[str, Any]]:
        return list(self.stream(sql, requested_limit=requested_limit))

    def stream(
        self, sql: str, requested_limit: int | None = None
    ) -> Iterator[dict[str, Any]]:
        expression = self.validate(sql, requested_limit=requested_limit)
        safe_sql = expression.sql(dialect=self.dialect)
        workspace = self._driver_workspace()
        if workspace is not None:
            yield from self._stream_driver(safe_sql)
            return
        connection = connections[self.database]
        total_rows = 0
        with transaction.atomic(using=self.database):
            with connection.cursor() as cursor:
                self._apply_read_only(cursor)
            cursor_factory = getattr(connection, "chunked_cursor", None)
            manager = cursor_factory() if cursor_factory else connection.cursor()
            with manager as cursor:
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
                        yield json_safe_row(dict(zip(columns, row)))

    def _explain_driver(self, safe_sql: str) -> dict[str, Any]:
        conn = self._open_driver()
        try:
            with conn.cursor() as cursor:
                self._apply_read_only(cursor)
                if self.engine == ENGINE_MYSQL:
                    cursor.execute(f"EXPLAIN FORMAT=JSON {safe_sql}")
                    row = cursor.fetchone()
                    plan = row[0] if row else None
                    return {"ok": True, "plan": plan, "sql": safe_sql}
                return {
                    "ok": True,
                    "skipped": True,
                    "sql": safe_sql,
                    "reason": "EXPLAIN is not implemented for this engine.",
                }
        finally:
            conn.close()

    def _stream_driver(self, safe_sql: str) -> Iterator[dict[str, Any]]:
        conn = self._open_driver()
        total_rows = 0
        try:
            cursor = conn.cursor()
            try:
                self._apply_read_only(cursor)
                cursor.execute(safe_sql)
                columns = [column[0] for column in (cursor.description or [])]
                while True:
                    rows = cursor.fetchmany(self.fetch_size)
                    if not rows:
                        break
                    for row in rows:
                        total_rows += 1
                        if total_rows > self.max_rows:
                            return
                        if isinstance(row, dict):
                            yield json_safe_row(row)
                        else:
                            yield json_safe_row(dict(zip(columns, row)))
            finally:
                cursor.close()
        finally:
            conn.close()

    def _open_driver(self):
        from connections.services.workspace import connect_database

        workspace = self.workspace
        return connect_database(
            engine=self.engine,
            host=workspace.host,
            port=workspace.port,
            db_name=workspace.db_name,
            db_user=workspace.db_user,
            password=workspace.get_password(),
        )


def executor_for_workspace(workspace, allowed_tables, allowed_columns, **kwargs):
    from connections.services.workspace import register_workspace_database

    engine = normalize_engine(getattr(workspace, "engine", ENGINE_POSTGRES))
    alias = "client"
    if engine == ENGINE_POSTGRES:
        alias = register_workspace_database(workspace)
    return ReadOnlySQLExecutor(
        database=alias,
        allowed_tables=set(allowed_tables or []),
        allowed_columns=allowed_columns or {},
        engine=engine,
        workspace=workspace,
        **kwargs,
    )
