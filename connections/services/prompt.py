from datetime import timedelta

from django.utils import timezone

from connections.models import DatabaseSchema
from connections.services.schema_discovery import (
    PostgreSQLSchemaDiscovery,
    transform_schema_for_llm,
)


semantic_config = {
    "tables": {
        "users": {
            "description": "Application users.",
        },
        "orders": {
            "description": "Customer purchase orders.",
            "columns": {
                "status": {
                    "values": [
                        "PENDING",
                        "CONFIRMED",
                        "SHIPPED",
                        "DELIVERED",
                        "CANCELLED",
                    ]
                },
                "payment_status": {
                    "values": [
                        "UNPAID",
                        "PAID",
                        "REFUNDED",
                    ]
                },
            },
        },
        "order_items": {
            "description": "Products contained in an order.",
        },
        "products": {
            "description": "Products available for sale.",
        },
    },
    "business_definitions": [
        "\"unpaid\" means orders.payment_status = 'UNPAID'",
        "\"paid\" means orders.payment_status = 'PAID'",
        '"revenue" means SUM(orders.total_amount) for paid orders',
    ],
}


class PromptGenerator:
    SCHEMA_MAX_AGE = timedelta(days=7)

    def generate(
        self,
        question: str,
        conversation_context: str = "",
    ) -> str:
        schema = self._get_schema()

        return self._build_prompt(
            question=question,
            conversation_context=conversation_context,
            schema=schema,
        )

    def _get_schema(self):
        schema_record = DatabaseSchema.objects.first()

        # No schema exists yet
        if schema_record is None:
            return self._discover_and_save()

        # Existing schema is still fresh
        if self._is_fresh(schema_record):
            return schema_record.schema_data

        # Schema is older than 7 days
        return self._discover_and_save(schema_record)

    def _is_fresh(self, schema_record: DatabaseSchema) -> bool:
        return timezone.now() - schema_record.discovered_at < self.SCHEMA_MAX_AGE

    def _discover_and_save(self, schema_record=None):
        discovery = PostgreSQLSchemaDiscovery()

        schema = discovery.discover()

        schema_data = transform_schema_for_llm(
            schema,
            semantic_config,
        )

        if schema_record is None:
            DatabaseSchema.objects.create(
                schema_data=schema_data,
            )
        else:
            schema_record.schema_data = schema_data
            schema_record.save(
                update_fields=[
                    "schema_data",
                    "discovered_at",
                ]
            )

        return schema_data

    def _build_prompt(
        self,
        question: str,
        conversation_context: str,
        schema,
    ) -> str:

        return f"""
You are a PostgreSQL SQL generation engine.

Your task is to convert the user's natural-language question into a valid PostgreSQL SQL query.

Use the provided database schema, business definitions, and relevant conversation context.

DATABASE SCHEMA:

{schema}


BUSINESS DEFINITIONS:

{self._format_business_definitions()}


RELEVANT CONVERSATION CONTEXT:

{conversation_context or "No previous conversation context."}


CURRENT USER QUESTION:

{question}


RULES:

- Only use tables and columns listed in the database schema.
- Never invent tables, columns, relationships, or values.
- Use foreign-key relationships when JOINs are required.
- Follow the business definitions exactly.
- Use previous conversation context only when it is relevant to the current question.
- The current user question has the highest priority.
- Do not assume business rules that are not provided.
- Generate only read-only SELECT queries.
- Do not generate INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, GRANT, REVOKE, or other write/DDL statements.
- Generate valid PostgreSQL syntax.
- Return only the SQL query.
- Do not include markdown.
- Do not include ```sql.
- Do not include explanations.
- Do not include comments.
""".strip()

    def _format_business_definitions(self) -> str:
        return "\n".join(
            f"- {definition}" for definition in semantic_config["business_definitions"]
        )
