from __future__ import annotations

from typing import Any

DISCOVERY_SQL = """
SELECT
    table_schema,
    table_name,
    column_name,
    data_type
FROM information_schema.columns
WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
ORDER BY table_schema, table_name, ordinal_position;
""".strip()

DISCOVERY_SQL_MYSQL = """
SELECT
    table_schema,
    table_name,
    column_name,
    data_type
FROM information_schema.columns
WHERE table_schema = DATABASE()
ORDER BY table_name, ordinal_position;
""".strip()

DISCOVERY_SQL_ORACLE = """
SELECT
    USER AS table_schema,
    table_name,
    column_name,
    data_type
FROM user_tab_columns
ORDER BY table_name, column_id
""".strip()

DISCOVERY_SQL_MSSQL = """
SELECT
    TABLE_SCHEMA,
    TABLE_NAME,
    COLUMN_NAME,
    DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION;
""".strip()


def discovery_sql_for(engine: str) -> str:
    from connections.services.engines import (
        ENGINE_MYSQL,
        ENGINE_MSSQL,
        ENGINE_ORACLE,
        normalize_engine,
    )

    engine = normalize_engine(engine)
    if engine == ENGINE_MYSQL:
        return DISCOVERY_SQL_MYSQL
    if engine == ENGINE_ORACLE:
        return DISCOVERY_SQL_ORACLE
    if engine == ENGINE_MSSQL:
        return DISCOVERY_SQL_MSSQL
    return DISCOVERY_SQL


def _row_value(row: Any, *keys: str, index: int | None = None) -> str:
    if isinstance(row, dict):
        lowered = {str(k).lower(): v for k, v in row.items()}
        for key in keys:
            if key.lower() in lowered and lowered[key.lower()] not in (None, ""):
                return str(lowered[key.lower()])
        return ""
    if index is not None and isinstance(row, (list, tuple)) and len(row) > index:
        value = row[index]
        return "" if value is None else str(value)
    return ""


def catalog_from_discovery_rows(rows: list[Any]) -> dict[str, Any]:
    tables: list[str] = []
    columns: dict[str, list[str]] = {}
    for row in rows or []:
        table = _row_value(row, "table_name", "tablename", index=1)
        column = _row_value(row, "column_name", "columnname", index=2)
        if not table:
            continue
        if table not in tables:
            tables.append(table)
        if column:
            bucket = columns.setdefault(table, [])
            if column not in bucket:
                bucket.append(column)
    return {"tables": tables, "columns": columns}


def columns_from_raw_schema(raw: dict[str, Any]) -> dict[str, list[str]]:
    columns: dict[str, list[str]] = {}
    for item in raw.get("columns") or []:
        if len(item) < 3:
            continue
        schema_name, table_name, column_name = item[0], item[1], item[2]
        if str(schema_name).startswith("pg_"):
            continue
        bucket = columns.setdefault(str(table_name), [])
        if str(column_name) not in bucket:
            bucket.append(str(column_name))
    return columns


def intersect_allow_lists(
    *,
    requested_tables: list[str],
    requested_columns: dict[str, list[str]] | None,
    discovered_tables: list[str],
    discovered_columns: dict[str, list[str]],
) -> tuple[list[str], dict[str, list[str]]]:
    live_tables = {str(name) for name in discovered_tables}
    allowed_tables = [name for name in requested_tables if name in live_tables]
    live_columns = {
        str(table): {str(col) for col in (cols or [])}
        for table, cols in (discovered_columns or {}).items()
    }
    allowed_columns: dict[str, list[str]] = {}
    requested_columns = requested_columns or {}
    for table in allowed_tables:
        wanted = requested_columns.get(table) or requested_columns.get(table.lower())
        if not wanted:
            continue
        allowed = [
            col
            for col in wanted
            if col in live_columns.get(table, set())
        ]
        if allowed:
            allowed_columns[table] = allowed
    allowed_tables = [name for name in allowed_tables if allowed_columns.get(name)]
    return allowed_tables, allowed_columns


def schema_text_from_catalog(
    tables: list[str],
    columns: dict[str, list[str]],
    engine: str = "postgres",
) -> str:
    from connections.services.engines import catalog_header, sql_language_name

    lines = [catalog_header(engine), ""]
    for table in tables:
        lines.append(f"TABLE: {table}")
        lines.append("Description: Discovered from your database.")
        lines.append("")
        lines.append("Columns:")
        lines.append("")
        for column in columns.get(table) or []:
            lines.append(f"- {column} TEXT")
        lines.append("")
    lines.extend(
        [
            "RULES:",
            "",
            "- Only use tables and columns listed above.",
            "- Never invent columns or tables.",
            f"- Return {sql_language_name(engine)} SQL only.",
        ]
    )
    return "\n".join(lines).strip()
