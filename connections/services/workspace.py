from __future__ import annotations

from typing import Any

import psycopg
from django.db import connections

from connections.services.catalog import columns_from_raw_schema, intersect_allow_lists
from connections.services.engine_discovery import discovery_for
from connections.services.engines import (
    ENGINE_MSSQL,
    ENGINE_MYSQL,
    ENGINE_ORACLE,
    ENGINE_POSTGRES,
    django_engine,
    normalize_engine,
)
from connections.services.schema_discovery import (
    PostgreSQLSchemaDiscovery,
    filter_schema_to_tables,
    transform_schema_for_llm,
)
from connections.services.semantic_layer import merge_semantic_layer


SUPERUSER_REFUSAL = (
    "QueryMind will not connect as a superuser or database owner. "
    "Create a dedicated read-only database role and use that instead."
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


def connect_database(
    *,
    engine: str = ENGINE_POSTGRES,
    host: str,
    port: int,
    db_name: str,
    db_user: str,
    password: str,
    timeout: int = 8,
):
    engine = normalize_engine(engine)
    try:
        if engine == ENGINE_POSTGRES:
            return connect_postgres(
                host=host,
                port=port,
                db_name=db_name,
                db_user=db_user,
                password=password,
                timeout=timeout,
            )
        if engine == ENGINE_MYSQL:
            import pymysql

            return pymysql.connect(
                host=host,
                port=int(port),
                database=db_name,
                user=db_user,
                password=password,
                connect_timeout=timeout,
                autocommit=True,
            )
        if engine == ENGINE_ORACLE:
            import oracledb

            dsn = oracledb.makedsn(host, int(port), service_name=db_name)
            return oracledb.connect(user=db_user, password=password, dsn=dsn)
        if engine == ENGINE_MSSQL:
            import pymssql

            return pymssql.connect(
                server=host,
                port=int(port),
                user=db_user,
                password=password,
                database=db_name,
                login_timeout=timeout,
            )
        raise WorkspaceConnectionError(f"Unsupported engine: {engine}")
    except WorkspaceConnectionError:
        raise
    except ImportError as exc:
        raise WorkspaceConnectionError(
            f"The {engine} driver is not installed on this server.",
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise WorkspaceConnectionError(explain_connection_error(exc), detail=str(exc)) from exc


def assert_safe_role(cursor, engine: str = ENGINE_POSTGRES) -> None:
    engine = normalize_engine(engine)
    if engine == ENGINE_POSTGRES:
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
        return
    if engine == ENGINE_MYSQL:
        cursor.execute("SELECT CURRENT_USER()")
        row = cursor.fetchone()
        identity = str(row[0] if row else "").lower()
        if identity.startswith("root@"):
            raise WorkspaceConnectionError(SUPERUSER_REFUSAL)
        return
    if engine == ENGINE_ORACLE:
        cursor.execute("SELECT USER FROM dual")
        return
    if engine == ENGINE_MSSQL:
        cursor.execute("SELECT IS_SRVROLEMEMBER('sysadmin')")
        row = cursor.fetchone()
        if row and row[0] == 1:
            raise WorkspaceConnectionError(SUPERUSER_REFUSAL)


def detect_readonly_role(cursor, table_names: list[str], engine: str = ENGINE_POSTGRES) -> bool:
    engine = normalize_engine(engine)
    if engine != ENGINE_POSTGRES:
        return False
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
        if str(schema_name).startswith("pg_") or str(schema_name).lower() in {
            "information_schema",
            "sys",
            "mysql",
            "performance_schema",
        }:
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
    engine: str = ENGINE_POSTGRES,
    allowed_tables: list[str] | None = None,
    allowed_columns: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    engine = normalize_engine(engine)
    conn = connect_database(
        engine=engine,
        host=host,
        port=port,
        db_name=db_name,
        db_user=db_user,
        password=password,
    )
    try:
        with conn.cursor() as cursor:
            assert_safe_role(cursor, engine)
            raw = discovery_for(engine).discover_with_cursor(cursor)
            names = table_names_from_raw(raw)
            discovered_columns = columns_from_raw_schema(raw)
            if not names:
                raise WorkspaceConnectionError(
                    "Connected, but QueryMind found no tables to use."
                )
            readonly = detect_readonly_role(cursor, names, engine)
        semantic = merge_semantic_layer(names)
        semantic["engine"] = engine
        schema_text = transform_schema_for_llm(raw, semantic)
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
            "semantic_layer": semantic,
            "is_readonly_role": readonly,
            "engine": engine,
        }
    finally:
        conn.close()


def apply_workspace_allow_list(workspace, *, requested_tables, requested_columns):
    """Update allow-lists from Your data without re-running the setup wizard."""
    import re

    discovered_tables = list(workspace.discovered_tables or [])
    discovered_columns = dict(workspace.discovered_columns or {})
    if not discovered_tables:
        discovered_tables = list(workspace.allowed_tables or [])
    if not discovered_columns:
        discovered_columns = dict(workspace.allowed_columns or {})
    allowed, allowed_columns = intersect_allow_lists(
        requested_tables=list(requested_tables or []),
        requested_columns=dict(requested_columns or {}),
        discovered_tables=discovered_tables,
        discovered_columns=discovered_columns,
    )
    if not allowed:
        raise WorkspaceConnectionError(
            "Choose at least one table and column QueryMind may use. This is a security boundary."
        )
    from connections.services.catalog import schema_text_from_catalog

    original = workspace.schema_text or ""
    has_all = all(
        re.search(rf"TABLE:\s+{re.escape(name)}\b", original, re.I) for name in allowed
    )
    source = (
        original
        if has_all
        else schema_text_from_catalog(
            discovered_tables,
            discovered_columns,
            getattr(workspace, "engine", ENGINE_POSTGRES),
        )
    )
    workspace.allowed_tables = allowed
    workspace.allowed_columns = allowed_columns
    workspace.schema_text = filter_schema_to_tables(source, allowed, allowed_columns)
    workspace.save(
        update_fields=["allowed_tables", "allowed_columns", "schema_text", "updated_at"]
    )
    return workspace


def refresh_workspace_schema(workspace):
    """Re-read live tables using stored credentials after process restart."""
    password = workspace.get_password() if workspace else ""
    if not workspace or not all(
        [workspace.host, workspace.db_name, workspace.db_user, password]
    ):
        return workspace
    try:
        live = discover_live_schema(
            host=workspace.host,
            port=workspace.port,
            db_name=workspace.db_name,
            db_user=workspace.db_user,
            password=password,
            engine=getattr(workspace, "engine", ENGINE_POSTGRES),
        )
    except WorkspaceConnectionError:
        return workspace
    allowed, allowed_columns = intersect_allow_lists(
        requested_tables=list(workspace.allowed_tables or []),
        requested_columns=dict(workspace.allowed_columns or {}),
        discovered_tables=live["tables"],
        discovered_columns=live["columns"],
    )
    workspace.discovered_tables = live["tables"]
    workspace.discovered_columns = live["columns"]
    workspace.is_readonly_role = live["is_readonly_role"]
    workspace.engine = live["engine"]
    if allowed:
        workspace.allowed_tables = allowed
        workspace.allowed_columns = allowed_columns
        workspace.schema_text = filter_schema_to_tables(
            live["schema_text"],
            allowed,
            allowed_columns,
        )
    else:
        workspace.schema_text = live["schema_text"]
    semantic = live.get("semantic_layer") or workspace.semantic_layer or {}
    workspace.semantic_layer = semantic
    workspace.save()
    return workspace


def register_workspace_database(workspace) -> str:
    alias = workspace.django_alias
    engine = normalize_engine(getattr(workspace, "engine", ENGINE_POSTGRES))
    connections.databases[alias] = {
        "ENGINE": django_engine(engine),
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
