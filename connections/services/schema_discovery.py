from __future__ import annotations

import re
from typing import Any

from django.db import connections

from connections.services.engines import catalog_header

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SKIP_TYPES = {
    "integer",
    "bigint",
    "smallint",
    "numeric",
    "double precision",
    "real",
    "timestamp with time zone",
    "timestamp without time zone",
    "date",
    "json",
    "jsonb",
    "bytea",
    "uuid",
}
_SKIP_NAME_PARTS = (
    "id",
    "email",
    "password",
    "token",
    "secret",
    "hash",
    "uuid",
    "phone",
    "ssn",
)


def _safe_ident(name: str) -> str:
    if not _IDENT.match(name or ""):
        raise ValueError(f"Unsafe identifier: {name!r}")
    return name


class PostgreSQLSchemaDiscovery:

    def __init__(self, alias="client"):
        self.alias = alias

    def discover_with_cursor(self, cursor):
        raw = {
            "tables": self.get_tables(cursor),
            "columns": self.get_columns(cursor),
            "primary_keys": self.get_primary_keys(cursor),
            "foreign_keys": self.get_foreign_keys(cursor),
            "unique_constraints": self.get_unique_constraints(cursor),
            "indexes": self.get_indexes(cursor),
            "table_comments": self.get_table_comments(cursor),
            "column_comments": self.get_column_comments(cursor),
        }
        raw["distinct_values"] = self.sample_distinct_values(cursor, raw)
        return raw

    def discover(self):
        connection = connections[self.alias]

        connection.ensure_connection()

        with connection.cursor() as cursor:
            return self.discover_with_cursor(cursor)

    def get_tables(self, cursor):
        cursor.execute(
            """
            SELECT
                table_schema,
                table_name
            FROM information_schema.tables
            WHERE table_schema NOT IN (
                'pg_catalog',
                'information_schema'
            )
            AND table_type = 'BASE TABLE'
            ORDER BY table_schema, table_name;
        """
        )

        return cursor.fetchall()

    def get_columns(self, cursor):
        cursor.execute(
            """
            SELECT
                table_schema,
                table_name,
                column_name,
                data_type,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_schema NOT IN (
                'pg_catalog',
                'information_schema'
            )
            ORDER BY
                table_schema,
                table_name,
                ordinal_position;
        """
        )

        return cursor.fetchall()

    def get_primary_keys(self, cursor):
        cursor.execute(
            """
            SELECT
                tc.table_schema,
                tc.table_name,
                kcu.column_name,
                tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
                AND tc.table_name = kcu.table_name
            WHERE tc.constraint_type = 'PRIMARY KEY'
            ORDER BY
                tc.table_schema,
                tc.table_name,
                kcu.ordinal_position;
        """
        )

        return cursor.fetchall()

    def get_foreign_keys(self, cursor):
        cursor.execute(
            """
            SELECT
                tc.table_schema,
                tc.table_name,
                kcu.column_name,
                ccu.table_schema AS referenced_table_schema,
                ccu.table_name AS referenced_table,
                ccu.column_name AS referenced_column,
                tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
                AND tc.table_name = kcu.table_name
            JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
            ORDER BY
                tc.table_schema,
                tc.table_name,
                kcu.column_name;
        """
        )

        return cursor.fetchall()

    def get_unique_constraints(self, cursor):
        cursor.execute(
            """
            SELECT
                tc.table_schema,
                tc.table_name,
                kcu.column_name,
                tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
                AND tc.table_name = kcu.table_name
            WHERE tc.constraint_type = 'UNIQUE'
            ORDER BY
                tc.table_schema,
                tc.table_name,
                kcu.ordinal_position;
        """
        )

        return cursor.fetchall()

    def get_indexes(self, cursor):
        cursor.execute(
            """
            SELECT
                schemaname,
                tablename,
                indexname,
                indexdef
            FROM pg_indexes
            WHERE schemaname NOT IN (
                'pg_catalog',
                'information_schema'
            )
            ORDER BY
                schemaname,
                tablename,
                indexname;
        """
        )

        return cursor.fetchall()

    def get_table_comments(self, cursor):
        cursor.execute(
            """
            SELECT
                n.nspname,
                c.relname,
                obj_description(c.oid, 'pg_class')
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'r'
              AND n.nspname NOT IN ('pg_catalog', 'information_schema');
            """
        )
        return cursor.fetchall()

    def get_column_comments(self, cursor):
        cursor.execute(
            """
            SELECT
                n.nspname,
                c.relname,
                a.attname,
                col_description(c.oid, a.attnum)
            FROM pg_attribute a
            JOIN pg_class c ON a.attrelid = c.oid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE a.attnum > 0
              AND NOT a.attisdropped
              AND c.relkind = 'r'
              AND n.nspname NOT IN ('pg_catalog', 'information_schema');
            """
        )
        return cursor.fetchall()

    def sample_distinct_values(self, cursor, raw: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
        pk_cols = {
            (str(item[1]), str(item[2]))
            for item in raw.get("primary_keys") or []
            if len(item) >= 3
        }
        samples: dict[str, dict[str, list[str]]] = {}
        for column in raw.get("columns") or []:
            if len(column) < 4:
                continue
            schema_name, table_name, column_name, data_type = column[:4]
            if str(schema_name).startswith("pg_"):
                continue
            dtype = str(data_type).lower()
            col_l = str(column_name).lower()
            if dtype in _SKIP_TYPES:
                continue
            if any(part in col_l for part in _SKIP_NAME_PARTS):
                continue
            if (str(table_name), str(column_name)) in pk_cols:
                continue
            try:
                table = _safe_ident(str(table_name))
                col = _safe_ident(str(column_name))
            except ValueError:
                continue
            try:
                cursor.execute("SET statement_timeout = 3000")
                cursor.execute(
                    f'SELECT COUNT(DISTINCT "{col}") FROM "{table}"'
                )
                count_row = cursor.fetchone()
                cardinality = int(count_row[0] or 0) if count_row else 0
                if cardinality <= 0 or cardinality > 50:
                    continue
                cursor.execute("SET statement_timeout = 3000")
                cursor.execute(
                    f"""
                    SELECT "{col}"::text, COUNT(*) AS n
                    FROM "{table}"
                    WHERE "{col}" IS NOT NULL
                    GROUP BY 1
                    ORDER BY n DESC
                    LIMIT 20
                    """
                )
                values = [str(row[0]) for row in cursor.fetchall() if row and row[0] is not None]
                if values:
                    samples.setdefault(str(table_name), {})[str(column_name)] = values
            except Exception:
                try:
                    cursor.execute("ROLLBACK")
                except Exception:
                    pass
                continue
        return samples


TYPE_MAPPING = {
    "character varying": "VARCHAR",
    "timestamp with time zone": "TIMESTAMPTZ",
    "timestamp without time zone": "TIMESTAMP",
    "integer": "INTEGER",
    "bigint": "BIGINT",
    "smallint": "SMALLINT",
    "numeric": "NUMERIC",
    "boolean": "BOOLEAN",
    "text": "TEXT",
    "date": "DATE",
    "double precision": "DOUBLE PRECISION",
    "real": "REAL",
    "json": "JSON",
    "jsonb": "JSONB",
}


def transform_schema_for_llm(
    raw_data: dict[str, Any],
    semantic_config: dict[str, Any] | None = None,
) -> str:
    """
    Transform raw PostgreSQL schema discovery data into
    an LLM-friendly schema description.

    Args:
        raw_data:
            Raw schema discovery response.

        semantic_config:
            Optional business descriptions, allowed values,
            business definitions, etc.

    Returns:
        LLM-friendly schema text.
    """

    semantic_config = semantic_config or {}

    schema = raw_data.get("schema", raw_data)

    tables = schema.get("tables", [])
    columns = schema.get("columns", [])
    primary_keys = schema.get("primary_keys", [])
    foreign_keys = schema.get("foreign_keys", [])
    unique_constraints = schema.get("unique_constraints", [])
    table_comments = {
        str(item[1]): str(item[2])
        for item in schema.get("table_comments") or []
        if len(item) >= 3 and item[2]
    }
    column_comments = {
        (str(item[1]), str(item[2])): str(item[3])
        for item in schema.get("column_comments") or []
        if len(item) >= 4 and item[3]
    }
    distinct_values = schema.get("distinct_values") or {}

    # ---------------------------------------------------------
    # Build table set
    # ---------------------------------------------------------

    table_names = []

    for table in tables:
        if len(table) < 2:
            continue

        schema_name, table_name = table[0], table[1]

        # Ignore PostgreSQL internal schemas
        if schema_name.startswith("pg_"):
            continue

        if table_name not in table_names:
            table_names.append(table_name)

    # ---------------------------------------------------------
    # Primary keys
    # ---------------------------------------------------------

    primary_key_columns: set[tuple[str, str]] = set()

    for item in primary_keys:
        if len(item) < 4:
            continue

        schema_name, table_name, column_name, constraint_name = item[:4]

        if schema_name.startswith("pg_"):
            continue

        primary_key_columns.add((table_name, column_name))

    # ---------------------------------------------------------
    # Foreign keys
    # ---------------------------------------------------------

    foreign_key_map: dict[tuple[str, str], tuple[str, str]] = {}

    relationships: list[dict[str, str]] = []

    for item in foreign_keys:
        if len(item) < 6:
            continue

        (
            source_schema,
            source_table,
            source_column,
            target_schema,
            target_table,
            target_column,
        ) = item[:6]

        if source_schema.startswith("pg_"):
            continue

        foreign_key_map[(source_table, source_column)] = (
            target_table,
            target_column,
        )

        relationships.append(
            {
                "source_table": source_table,
                "source_column": source_column,
                "target_table": target_table,
                "target_column": target_column,
            }
        )

    # ---------------------------------------------------------
    # Unique columns
    # ---------------------------------------------------------

    unique_columns: set[tuple[str, str]] = set()

    for item in unique_constraints:
        if len(item) < 4:
            continue

        schema_name, table_name, column_name, constraint_name = item[:4]

        if schema_name.startswith("pg_"):
            continue

        unique_columns.add((table_name, column_name))

    # ---------------------------------------------------------
    # Columns grouped by table
    # ---------------------------------------------------------

    table_columns: dict[str, list[dict[str, Any]]] = {
        table_name: [] for table_name in table_names
    }

    for column in columns:
        if len(column) < 6:
            continue

        (
            schema_name,
            table_name,
            column_name,
            data_type,
            nullable,
            default_value,
        ) = column[:6]

        if schema_name.startswith("pg_"):
            continue

        if table_name not in table_columns:
            table_columns[table_name] = []

        table_columns[table_name].append(
            {
                "name": column_name,
                "type": TYPE_MAPPING.get(
                    str(data_type).lower(),
                    str(data_type).upper(),
                ),
                "nullable": nullable == "YES",
                "default": default_value,
                "primary_key": (
                    table_name,
                    column_name,
                )
                in primary_key_columns,
                "unique": (
                    table_name,
                    column_name,
                )
                in unique_columns,
                "foreign_key": foreign_key_map.get((table_name, column_name)),
            }
        )

    # ---------------------------------------------------------
    # Generate LLM-friendly output
    # ---------------------------------------------------------

    output: list[str] = []

    output.append(catalog_header(semantic_config.get("engine")))
    output.append("")

    for table_name in table_names:

        table_config = semantic_config.get("tables", {}).get(table_name, {})

        description = table_config.get("description") or table_comments.get(table_name)

        output.append(f"TABLE: {table_name}")

        if description:
            output.append(f"Description: {description}")
        else:
            output.append("Description: No description available.")

        pk_names = [name for t, name in primary_key_columns if t == table_name]
        if pk_names:
            output.append("Grain: one row per " + ", ".join(pk_names))
        fan_outs = [
            rel
            for rel in relationships
            if rel["target_table"] == table_name
        ]
        if fan_outs:
            output.append(
                "Fan-out: "
                + "; ".join(
                    f"{rel['source_table']}.{rel['source_column']} → many {table_name}"
                    for rel in fan_outs
                )
            )

        output.append("")
        output.append("Columns:")
        output.append("")

        for column in table_columns.get(table_name, []):
            parts = [
                column["name"],
                column["type"],
            ]

            if column["primary_key"]:
                parts.append("PRIMARY KEY")

            if not column["nullable"]:
                parts.append("NOT NULL")

            if column["unique"]:
                parts.append("UNIQUE")

            if column["foreign_key"]:
                target_table, target_column = column["foreign_key"]

                parts.append(f"→ {target_table}.{target_column}")

            comment = column_comments.get((table_name, column["name"]))
            if comment:
                parts.append(f"-- {comment}")

            output.append("- " + " ".join(parts))

            values = (
                table_config.get("columns", {}).get(column["name"], {}).get("values")
            )
            if not values:
                values = (distinct_values.get(table_name) or {}).get(column["name"])

            if values:
                output.append("  Values: " + ", ".join(str(v) for v in values))

        output.append("")

    # ---------------------------------------------------------
    # Relationships
    # ---------------------------------------------------------

    if relationships:

        output.append("RELATIONSHIPS:")
        output.append("")

        for relationship in relationships:

            output.append(
                "- "
                f"{relationship['source_table']}."
                f"{relationship['source_column']} "
                "→ "
                f"{relationship['target_table']}."
                f"{relationship['target_column']}"
            )

        output.append("")

    # ---------------------------------------------------------
    # Business definitions
    # ---------------------------------------------------------

    business_definitions = semantic_config.get("business_definitions", [])

    if business_definitions:

        output.append("BUSINESS DEFINITIONS:")
        output.append("")

        for definition in business_definitions:
            output.append(f"- {definition}")

        output.append("")

    # ---------------------------------------------------------
    # Rules
    # ---------------------------------------------------------

    rules = semantic_config.get(
        "rules",
        [
            "Only use tables and columns listed above.",
            "Never invent columns.",
            "Use foreign-key relationships for JOINs.",
            "Do not aggregate a one-side column after a 1-to-many join.",
            "Respect Grain and Fan-out notes when choosing SUM/COUNT.",
        ],
    )

    output.append("RULES:")
    output.append("")

    for rule in rules:
        output.append(f"- {rule}")

    return "\n".join(output)


def _definition_uses_only_kept_tables(line: str, kept_tables: set[str]) -> bool:
    mentioned = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\.", line)
    if not mentioned:
        return True
    return all(name.lower() in kept_tables for name in mentioned)


def filter_schema_to_tables(
    schema_text: str,
    allowed_tables: list[str] | set[str],
    allowed_columns: dict[str, list[str]] | None = None,
) -> str:
    """Keep only allow-listed tables and columns in LLM schema text."""
    allowed = {str(name).lower() for name in (allowed_tables or []) if name}
    if not schema_text or not allowed:
        return ""

    columns_by_table: dict[str, set[str]] = {}
    if allowed_columns:
        for table, cols in allowed_columns.items():
            columns_by_table[str(table).lower()] = {
                str(col).lower() for col in (cols or []) if col
            }

    header = "DATABASE: PostgreSQL"
    for line in (schema_text or "").splitlines()[:8]:
        if line.startswith("DATABASE:"):
            header = line.strip()
            break
    result = [header, ""]
    table_pattern = re.compile(
        r"(TABLE:\s+(\w+).*?)(?=\n\nTABLE:|\n\nRELATIONSHIPS:|\n\nBUSINESS DEFINITIONS:|\n\nRULES:|$)",
        re.DOTALL,
    )
    kept_tables: set[str] = set()
    for table_block, table_name in table_pattern.findall(schema_text):
        if table_name.lower() not in allowed:
            continue
        kept_tables.add(table_name.lower())
        allowed_for_table = columns_by_table.get(table_name.lower())
        if allowed_columns is not None and not allowed_for_table:
            continue
        if allowed_for_table:
            filtered_lines = []
            keep_values = False
            for line in table_block.strip().splitlines():
                match = re.match(r"^- (\w+)\s+", line.strip())
                if match:
                    keep_values = match.group(1).lower() in allowed_for_table
                    if keep_values:
                        filtered_lines.append(line)
                    continue
                stripped = line.strip()
                if stripped.lower().startswith("values:"):
                    if keep_values:
                        filtered_lines.append(line)
                    continue
                filtered_lines.append(line)
            result.append("\n".join(filtered_lines).strip())
        else:
            result.append(table_block.strip())
        result.append("")

    relationships_match = re.search(
        r"RELATIONSHIPS:\s*(.*?)(?=\n\nBUSINESS DEFINITIONS:|\n\nRULES:|$)",
        schema_text,
        re.DOTALL,
    )
    if relationships_match:
        relationships = []
        for line in relationships_match.group(1).splitlines():
            line = line.strip()
            if not line.startswith("-"):
                continue
            match = re.match(
                r"-\s+(\w+)\.(\w+)\s+→\s+(\w+)\.(\w+)",
                line,
            )
            if not match:
                continue
            from_table, from_col, to_table, to_col = (
                match.group(1).lower(),
                match.group(2).lower(),
                match.group(3).lower(),
                match.group(4).lower(),
            )
            if from_table not in kept_tables or to_table not in kept_tables:
                continue
            from_allowed = columns_by_table.get(from_table)
            to_allowed = columns_by_table.get(to_table)
            if from_allowed and from_col not in from_allowed:
                continue
            if to_allowed and to_col not in to_allowed:
                continue
            relationships.append(line)
        if relationships:
            result.append("RELATIONSHIPS:")
            result.extend(relationships)
            result.append("")

    definitions_match = re.search(
        r"BUSINESS DEFINITIONS:\s*(.*?)(?=\n\nRULES:|$)",
        schema_text,
        re.DOTALL,
    )
    if definitions_match:
        kept_defs = []
        for line in definitions_match.group(1).splitlines():
            stripped = line.strip()
            if not stripped.startswith("-"):
                continue
            if _definition_uses_only_kept_tables(stripped, kept_tables):
                kept_defs.append(stripped)
        if kept_defs:
            result.append("BUSINESS DEFINITIONS:")
            result.extend(kept_defs)
            result.append("")

    result.extend(
        [
            "RULES:",
            "",
            "- Only use tables and columns listed above.",
            "- Never invent columns or tables.",
            "- Use foreign-key relationships for JOINs.",
            "- Return SQL only for the database named in DATABASE: above.",
            "- Treat tables and columns that are not listed as if they do not exist.",
            "- Do not aggregate a one-side column after a 1-to-many join.",
            "- Respect Grain and Fan-out notes when choosing SUM/COUNT.",
        ]
    )
    return "\n".join(result).strip()


def extract_relationships_from_schema(schema_text: str) -> list[dict[str, str]]:
    relationships: list[dict[str, str]] = []
    match = re.search(
        r"RELATIONSHIPS:\s*(.*?)(?=\n\nBUSINESS DEFINITIONS:|\n\nRULES:|$)",
        schema_text or "",
        re.DOTALL,
    )
    if not match:
        return relationships
    for line in match.group(1).splitlines():
        line = line.strip()
        parsed = re.match(
            r"-\s+(\w+)\.(\w+)\s+→\s+(\w+)\.(\w+)",
            line,
        )
        if not parsed:
            continue
        relationships.append(
            {
                "source_table": parsed.group(1),
                "source_column": parsed.group(2),
                "target_table": parsed.group(3),
                "target_column": parsed.group(4),
            }
        )
    return relationships
