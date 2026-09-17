from __future__ import annotations

from typing import Any

from connections.services.engines import ENGINE_MYSQL, ENGINE_MSSQL, ENGINE_ORACLE


class MySQLSchemaDiscovery:
    def discover_with_cursor(self, cursor) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """
        )
        tables = cursor.fetchall()
        cursor.execute(
            """
            SELECT table_schema, table_name, column_name, data_type,
                   is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
            ORDER BY table_name, ordinal_position
            """
        )
        columns = cursor.fetchall()
        cursor.execute(
            """
            SELECT table_schema, table_name, column_name, constraint_name
            FROM information_schema.key_column_usage
            WHERE table_schema = DATABASE()
              AND constraint_name = 'PRIMARY'
            """
        )
        primary_keys = cursor.fetchall()
        cursor.execute(
            """
            SELECT
                kcu.table_schema,
                kcu.table_name,
                kcu.column_name,
                kcu.referenced_table_schema,
                kcu.referenced_table_name,
                kcu.referenced_column_name,
                kcu.constraint_name
            FROM information_schema.key_column_usage kcu
            WHERE kcu.table_schema = DATABASE()
              AND kcu.referenced_table_name IS NOT NULL
            """
        )
        foreign_keys = cursor.fetchall()
        return {
            "tables": tables,
            "columns": columns,
            "primary_keys": primary_keys,
            "foreign_keys": foreign_keys,
            "unique_constraints": [],
            "indexes": [],
            "table_comments": [],
            "column_comments": [],
            "distinct_values": {},
        }


class OracleSchemaDiscovery:
    def discover_with_cursor(self, cursor) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT USER AS table_schema, table_name
            FROM user_tables
            ORDER BY table_name
            """
        )
        tables = cursor.fetchall()
        cursor.execute(
            """
            SELECT USER, table_name, column_name, data_type,
                   nullable, data_default
            FROM user_tab_columns
            ORDER BY table_name, column_id
            """
        )
        columns = cursor.fetchall()
        cursor.execute(
            """
            SELECT USER, acc.table_name, acc.column_name, ac.constraint_name
            FROM user_constraints ac
            JOIN user_cons_columns acc
              ON ac.constraint_name = acc.constraint_name
            WHERE ac.constraint_type = 'P'
            """
        )
        primary_keys = cursor.fetchall()
        cursor.execute(
            """
            SELECT
                USER,
                acc.table_name,
                acc.column_name,
                USER,
                rcc.table_name,
                rcc.column_name,
                ac.constraint_name
            FROM user_constraints ac
            JOIN user_cons_columns acc
              ON ac.constraint_name = acc.constraint_name
            JOIN user_cons_columns rcc
              ON ac.r_constraint_name = rcc.constraint_name
            WHERE ac.constraint_type = 'R'
            """
        )
        foreign_keys = cursor.fetchall()
        return {
            "tables": tables,
            "columns": columns,
            "primary_keys": primary_keys,
            "foreign_keys": foreign_keys,
            "unique_constraints": [],
            "indexes": [],
            "table_comments": [],
            "column_comments": [],
            "distinct_values": {},
        }


class MSSQLSchemaDiscovery:
    def discover_with_cursor(self, cursor) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT TABLE_SCHEMA, TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_SCHEMA, TABLE_NAME
            """
        )
        tables = cursor.fetchall()
        cursor.execute(
            """
            SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE,
                   IS_NULLABLE, COLUMN_DEFAULT
            FROM INFORMATION_SCHEMA.COLUMNS
            ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION
            """
        )
        columns = cursor.fetchall()
        cursor.execute(
            """
            SELECT
                kcu.TABLE_SCHEMA,
                kcu.TABLE_NAME,
                kcu.COLUMN_NAME,
                tc.CONSTRAINT_NAME
            FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
            JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
              ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
             AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
            WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
            """
        )
        primary_keys = cursor.fetchall()
        cursor.execute(
            """
            SELECT
                fk.TABLE_SCHEMA,
                fk.TABLE_NAME,
                fkc.COLUMN_NAME,
                pk.TABLE_SCHEMA,
                pk.TABLE_NAME,
                pkc.COLUMN_NAME,
                fk.CONSTRAINT_NAME
            FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc
            JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS fk
              ON rc.CONSTRAINT_NAME = fk.CONSTRAINT_NAME
            JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS pk
              ON rc.UNIQUE_CONSTRAINT_NAME = pk.CONSTRAINT_NAME
            JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE fkc
              ON fk.CONSTRAINT_NAME = fkc.CONSTRAINT_NAME
            JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE pkc
              ON pk.CONSTRAINT_NAME = pkc.CONSTRAINT_NAME
             AND fkc.ORDINAL_POSITION = pkc.ORDINAL_POSITION
            """
        )
        foreign_keys = cursor.fetchall()
        return {
            "tables": tables,
            "columns": columns,
            "primary_keys": primary_keys,
            "foreign_keys": foreign_keys,
            "unique_constraints": [],
            "indexes": [],
            "table_comments": [],
            "column_comments": [],
            "distinct_values": {},
        }


def discovery_for(engine: str):
    from connections.services.schema_discovery import PostgreSQLSchemaDiscovery

    if engine == ENGINE_MYSQL:
        return MySQLSchemaDiscovery()
    if engine == ENGINE_ORACLE:
        return OracleSchemaDiscovery()
    if engine == ENGINE_MSSQL:
        return MSSQLSchemaDiscovery()
    return PostgreSQLSchemaDiscovery()
