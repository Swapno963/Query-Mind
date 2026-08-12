from django.db import connections


class PostgreSQLSchemaDiscovery:

    def __init__(self, alias="client"):
        self.alias = alias

    def discover(self):
        connection = connections[self.alias]

        connection.ensure_connection()

        with connection.cursor() as cursor:
            return {
                "tables": self.get_tables(cursor),
                "columns": self.get_columns(cursor),
                "primary_keys": self.get_primary_keys(cursor),
                "foreign_keys": self.get_foreign_keys(cursor),
                "unique_constraints": self.get_unique_constraints(cursor),
                "indexes": self.get_indexes(cursor),
            }

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


from typing import Any


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

    output.append("DATABASE: PostgreSQL")
    output.append("")

    for table_name in table_names:

        table_config = semantic_config.get("tables", {}).get(table_name, {})

        description = table_config.get("description")

        output.append(f"TABLE: {table_name}")

        if description:
            output.append(f"Description: {description}")
        else:
            output.append("Description: No description available.")

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

            output.append("- " + " ".join(parts))

            # Allowed values
            values = (
                table_config.get("columns", {}).get(column["name"], {}).get("values")
            )

            if values:
                output.append("  Values: " + ", ".join(values))

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
            "Return PostgreSQL SQL only.",
        ],
    )

    output.append("RULES:")
    output.append("")

    for rule in rules:
        output.append(f"- {rule}")

    return "\n".join(output)
