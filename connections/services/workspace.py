from __future__ import annotations

from typing import Any

import psycopg
from django.db import connections

from connections.services.schema_discovery import (
    PostgreSQLSchemaDiscovery,
    filter_schema_to_tables,
    transform_schema_for_llm,
)
from connections.services.catalog import columns_from_raw_schema


SUPERUSER_REFUSAL = (
    "QueryMind will not connect as a superuser or database owner. "
    "Create a dedicated read-only PostgreSQL role and use that instead."
)


class WorkspaceConnectionError(Exception):
    def __init__(self, user_message: str, detail: str = ""):
        super().__init__(user_message)
        self.user_message = user_message
        self.detail = detail


def explain_connection_error(exc: BaseException) -> str:
    msg = str(exc).lower()
    if "password" in msg or "authentication" in msg or "auth" in msg:
        return "Could not sign in to the database. Check the username and password."
    if "could not translate host" in msg or "name or service not known" in msg:
        return "Could not find that database host. Check the host name."
    if (
        "connection refused" in msg
        or "could not connect" in msg
        or "timeout" in msg
        or "timed out" in msg
    ):
        return "Could not reach the database. Check the host, port, and network."
    if "does not exist" in msg and "database" in msg:
        return "That database name was not found on the server."
    return "Could not connect to the database. Check the host, credentials, and network."


def connect_postgres(
    *,
    host: str,
    port: int,
    db_name: str,
    db_user: str,
    password: str,
    timeout: int = 8,
):
    try:
        return psycopg.connect(
            host=host,
            port=int(port),
            dbname=db_name,
            user=db_user,
            password=password,
            connect_timeout=timeout,
            autocommit=True,
        )
    except Exception as exc:
        raise WorkspaceConnectionError(explain_connection_error(exc), detail=str(exc)) from exc


def assert_safe_role(cursor) -> None:
    cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
    row = cursor.fetchone()
    if row and row[0]:
        raise WorkspaceConnectionError(SUPERUSER_REFUSAL)

    cursor.execute(
        """
        SELECT pg_catalog.pg_get_userbyid(datdba) = current_user
        FROM pg_database
        WHERE datname = current_database()
        """
    )
    row = cursor.fetchone()
    if row and row[0]:
        raise WorkspaceConnectionError(SUPERUSER_REFUSAL)


def detect_readonly_role(cursor, table_names: list[str]) -> bool:
    cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
    row = cursor.fetchone()
    if row and row[0]:
        return False

    for table in table_names:
        qualified = f"public.{table}" if "." not in table else table
        cursor.execute(
            """
            SELECT
                has_table_privilege(current_user, %s, 'INSERT')
                OR has_table_privilege(current_user, %s, 'UPDATE')
                OR has_table_privilege(current_user, %s, 'DELETE')
                OR has_table_privilege(current_user, %s, 'TRUNCATE')
            """,
            [qualified, qualified, qualified, qualified],
        )
        write_row = cursor.fetchone()
        if write_row and write_row[0]:
            return False
    return True


def table_names_from_raw(raw: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for table in raw.get("tables") or []:
        if len(table) < 2:
            continue
        schema_name, table_name = table[0], table[1]
        if str(schema_name).startswith("pg_"):
            continue
        if table_name not in names:
            names.append(str(table_name))
    return names


def discover_live_schema(
    *,
    host: str,
    port: int,
    db_name: str,
    db_user: str,
    password: str,
    allowed_tables: list[str] | None = None,
    allowed_columns: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    conn = connect_postgres(
        host=host,
        port=port,
        db_name=db_name,
        db_user=db_user,
        password=password,
    )
    try:
        with conn.cursor() as cursor:
            assert_safe_role(cursor)
            raw = PostgreSQLSchemaDiscovery().discover_with_cursor(cursor)
            names = table_names_from_raw(raw)
            discovered_columns = columns_from_raw_schema(raw)
            if not names:
                raise WorkspaceConnectionError(
                    "Connected, but QueryMind found no tables to use."
                )
            readonly = detect_readonly_role(cursor, names)
        schema_text = transform_schema_for_llm(raw)
        if allowed_tables:
            schema_text = filter_schema_to_tables(
                schema_text,
                allowed_tables,
                allowed_columns,
            )
        return {
            "tables": names,
            "columns": discovered_columns,
            "schema_text": schema_text,
            "is_readonly_role": readonly,
        }
    finally:
        conn.close()


def register_workspace_database(workspace) -> str:
    alias = workspace.django_alias
    connections.databases[alias] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": workspace.db_name,
        "USER": workspace.db_user,
        "PASSWORD": workspace.get_password(),
        "HOST": workspace.host,
        "PORT": str(workspace.port),
        "ATOMIC_REQUESTS": False,
        "AUTOCOMMIT": True,
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": False,
        "OPTIONS": {},
        "TIME_ZONE": None,
        "DISABLE_SERVER_SIDE_CURSORS": False,
    }
    try:
        connections[alias].close()
    except Exception:
        pass
    return alias
