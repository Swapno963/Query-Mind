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
