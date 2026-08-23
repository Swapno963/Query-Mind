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


multi_tenent_schema = """
DATABASE: MySQL (per-tenant database, e.g. tenant_{store_name})

TABLE: users
Description: Tenant admin / store users.

Columns: • id BIGINT UNSIGNED PRIMARY KEY NOT NULL (auto increment)
• name VARCHAR(255) NOT NULL
• email VARCHAR(255) NOT NULL UNIQUE
• email_verified_at TIMESTAMP NULL
• password VARCHAR(255) NOT NULL
• remember_token VARCHAR(100) NULL
• created_at TIMESTAMP NULL
• updated_at TIMESTAMP NULL

TABLE: password_reset_tokens
Description: Password reset tokens.

Columns: • email VARCHAR(255) PRIMARY KEY NOT NULL
• token VARCHAR(255) NOT NULL
• created_at TIMESTAMP NULL

TABLE: sessions
Description: Session store.

Columns: • id VARCHAR(255) PRIMARY KEY NOT NULL
• user_id BIGINT UNSIGNED NULL (indexed → users.id, no FK constraint)
• ip_address VARCHAR(45) NULL
• user_agent TEXT NULL
• payload LONGTEXT NOT NULL
• last_activity INT NOT NULL (indexed)

TABLE: cache
Description: Application cache.

Columns: • key VARCHAR(255) PRIMARY KEY NOT NULL
• value MEDIUMTEXT NOT NULL
• expiration INT NOT NULL

TABLE: cache_locks
Description: Cache locks.

Columns: • key VARCHAR(255) PRIMARY KEY NOT NULL
• owner VARCHAR(255) NOT NULL
• expiration INT NOT NULL

TABLE: jobs
Description: Queued jobs.

Columns: • id BIGINT UNSIGNED PRIMARY KEY NOT NULL
• queue VARCHAR(255) NOT NULL (indexed)
• payload LONGTEXT NOT NULL
• attempts TINYINT UNSIGNED NOT NULL
• reserved_at INT UNSIGNED NULL
• available_at INT UNSIGNED NOT NULL
• created_at INT UNSIGNED NOT NULL

TABLE: job_batches
Description: Job batch metadata.

Columns: • id VARCHAR(255) PRIMARY KEY NOT NULL
• name VARCHAR(255) NOT NULL
• total_jobs INT NOT NULL
• pending_jobs INT NOT NULL
• failed_jobs INT NOT NULL
• failed_job_ids LONGTEXT NOT NULL
• options MEDIUMTEXT NULL
• cancelled_at INT NULL
• created_at INT NOT NULL
• finished_at INT NULL

TABLE: failed_jobs
Description: Failed queue jobs.

Columns: • id BIGINT UNSIGNED PRIMARY KEY NOT NULL
• uuid VARCHAR(255) NOT NULL UNIQUE
• connection TEXT NOT NULL
• queue TEXT NOT NULL
• payload LONGTEXT NOT NULL
• exception LONGTEXT NOT NULL
• failed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP

TABLE: categories
Description: Product categories.

Columns: • id BIGINT UNSIGNED PRIMARY KEY NOT NULL
• name VARCHAR(80) NOT NULL
• slug VARCHAR(255) NOT NULL UNIQUE
• description VARCHAR(160) NULL
• image VARCHAR(255) NULL
• status ENUM('active','inactive') NOT NULL DEFAULT 'active'
• created_at TIMESTAMP NULL
• updated_at TIMESTAMP NULL

TABLE: products
Description: Products available for sale.

Columns: • id BIGINT UNSIGNED PRIMARY KEY NOT NULL
• category_id BIGINT UNSIGNED NULL → categories.id (nullOnDelete)
• name VARCHAR(255) NOT NULL
• slug VARCHAR(255) NOT NULL UNIQUE
• short_description VARCHAR(155) NULL
• description LONGTEXT NULL
• price DECIMAL(12,2) NOT NULL
• compare_price DECIMAL(12,2) NULL
• cost DECIMAL(12,2) NULL
• serial VARCHAR(255) NULL
• sku VARCHAR(255) NULL UNIQUE
• unit VARCHAR(30) NOT NULL DEFAULT 'Piece'
• quantity INT UNSIGNED NULL
• warranty VARCHAR(255) NULL
• sold_count INT UNSIGNED NOT NULL DEFAULT 0
• brand VARCHAR(255) NULL
• seo_title VARCHAR(255) NULL
• video_url VARCHAR(255) NULL
• status ENUM('draft','active','archived') NOT NULL DEFAULT 'draft'
• created_at TIMESTAMP NULL
• updated_at TIMESTAMP NULL

TABLE: product_images
Description: Product gallery images.

Columns: • id BIGINT UNSIGNED PRIMARY KEY NOT NULL
• product_id BIGINT UNSIGNED NOT NULL → products.id (cascadeOnDelete)
• path VARCHAR(255) NOT NULL
• sort_order TINYINT UNSIGNED NOT NULL DEFAULT 0
• is_cover BOOLEAN NOT NULL DEFAULT false
• created_at TIMESTAMP NULL
• updated_at TIMESTAMP NULL

TABLE: product_variants
Description: Variant groups on a product (e.g. Size, Color).

Columns: • id BIGINT UNSIGNED PRIMARY KEY NOT NULL
• product_id BIGINT UNSIGNED NOT NULL → products.id (cascadeOnDelete)
• title VARCHAR(255) NOT NULL
• is_mandatory BOOLEAN NOT NULL DEFAULT true
• sort_order TINYINT UNSIGNED NOT NULL DEFAULT 0
• created_at TIMESTAMP NULL
• updated_at TIMESTAMP NULL

TABLE: product_variant_options
Description: Options under a variant group (with optional extra price).

Columns: • id BIGINT UNSIGNED PRIMARY KEY NOT NULL
• product_variant_id BIGINT UNSIGNED NOT NULL → product_variants.id (cascadeOnDelete)
• attribute VARCHAR(255) NOT NULL
• extra_price DECIMAL(12,2) NOT NULL DEFAULT 0
• sort_order TINYINT UNSIGNED NOT NULL DEFAULT 0
• created_at TIMESTAMP NULL
• updated_at TIMESTAMP NULL

TABLE: product_details
Description: Product specification name/value rows.

Columns: • id BIGINT UNSIGNED PRIMARY KEY NOT NULL
• product_id BIGINT UNSIGNED NOT NULL → products.id (cascadeOnDelete)
• name VARCHAR(255) NOT NULL
• value VARCHAR(255) NOT NULL
• sort_order TINYINT UNSIGNED NOT NULL DEFAULT 0
• created_at TIMESTAMP NULL
• updated_at TIMESTAMP NULL

TABLE: orders
Description: Customer / POS purchase orders.

Columns: • id BIGINT UNSIGNED PRIMARY KEY NOT NULL
• order_number VARCHAR(255) NOT NULL UNIQUE
• receipt_token VARCHAR(32) NULL UNIQUE
• customer_name VARCHAR(255) NULL
• customer_phone VARCHAR(30) NULL
• customer_email VARCHAR(255) NULL
• country_code VARCHAR(10) NOT NULL DEFAULT '+880'
• address VARCHAR(255) NULL
• delivery_area VARCHAR(20) NULL
Values: inside, outside
• payment_method VARCHAR(30) NOT NULL DEFAULT 'cod'
Values: cod
• order_type VARCHAR(20) NULL
Values: in_shop, online
• note TEXT NULL
• promo_code VARCHAR(255) NULL
• status VARCHAR(30) NOT NULL DEFAULT 'placed'
Values: placed, on_hold, confirmed, shipped, delivered, completed, cancelled, returned, payment_on_process, payment_failed
• stock_adjusted BOOLEAN NOT NULL DEFAULT false
• subtotal DECIMAL(12,2) NOT NULL DEFAULT 0
• discount_amount DECIMAL(12,2) NOT NULL DEFAULT 0
• discount_percent DECIMAL(5,2) NOT NULL DEFAULT 0
• vat_percent DECIMAL(5,2) NOT NULL DEFAULT 0
• vat_amount DECIMAL(12,2) NOT NULL DEFAULT 0
• delivery_charge DECIMAL(12,2) NOT NULL DEFAULT 0
• total DECIMAL(12,2) NOT NULL DEFAULT 0
• paid_amount DECIMAL(12,2) NOT NULL DEFAULT 0
• created_at TIMESTAMP NULL
• updated_at TIMESTAMP NULL

TABLE: order_items
Description: Products contained in an order.

Columns: • id BIGINT UNSIGNED PRIMARY KEY NOT NULL
• order_id BIGINT UNSIGNED NOT NULL → orders.id (cascadeOnDelete)
• product_id BIGINT UNSIGNED NULL → products.id (nullOnDelete)
• product_name VARCHAR(255) NOT NULL
• product_image TEXT NULL
• variants JSON NULL
• unit_price DECIMAL(12,2) NOT NULL
• quantity INT UNSIGNED NOT NULL
• warranty VARCHAR(120) NULL
• line_total DECIMAL(12,2) NOT NULL
• created_at TIMESTAMP NULL
• updated_at TIMESTAMP NULL

TABLE: promo_codes
Description: Discount / promo codes.

Columns: • id BIGINT UNSIGNED PRIMARY KEY NOT NULL
• code VARCHAR(255) NOT NULL UNIQUE
• discount_type ENUM('amount','percentage') NOT NULL
• discount_value DECIMAL(12,2) NOT NULL
• min_purchase_enabled BOOLEAN NOT NULL DEFAULT false
• min_purchase_amount DECIMAL(12,2) NULL
• expires_at DATE NULL
• created_at TIMESTAMP NULL
• updated_at TIMESTAMP NULL

TABLE: shop_settings
Description: Shop profile, delivery charges, and feature toggles.

Columns: • id BIGINT UNSIGNED PRIMARY KEY NOT NULL
• business_name VARCHAR(255) NOT NULL
• business_type VARCHAR(255) NULL
• email VARCHAR(255) NULL
• phone VARCHAR(255) NULL
• address VARCHAR(255) NULL
• description TEXT NULL
• announcement VARCHAR(255) NULL
• language VARCHAR(5) NOT NULL DEFAULT 'en'
• vat_percent DECIMAL(5,2) NOT NULL DEFAULT 0
• delivery_inside_charge DECIMAL(12,2) NOT NULL DEFAULT 70
• delivery_outside_charge DECIMAL(12,2) NOT NULL DEFAULT 130
• enable_promo_code BOOLEAN NOT NULL DEFAULT false
• maintain_stock BOOLEAN NOT NULL DEFAULT false
• show_sold_count BOOLEAN NOT NULL DEFAULT false
• logo_path VARCHAR(255) NULL
• favicon_path VARCHAR(255) NULL
• theme_color VARCHAR(7) NOT NULL DEFAULT '#2563eb'
• created_at TIMESTAMP NULL
• updated_at TIMESTAMP NULL

TABLE: shop_policies
Description: Shop legal / policy pages.

Columns: • id BIGINT UNSIGNED PRIMARY KEY NOT NULL
• about_us LONGTEXT NULL
• privacy_policy LONGTEXT NULL
• terms_and_conditions LONGTEXT NULL
• return_and_cancellation LONGTEXT NULL
• created_at TIMESTAMP NULL
• updated_at TIMESTAMP NULL

TABLE: shop_chat_settings
Description: Facebook / WhatsApp chat widget settings.

Columns: • id BIGINT UNSIGNED PRIMARY KEY NOT NULL
• facebook_enabled BOOLEAN NOT NULL DEFAULT false
• facebook_page_id VARCHAR(255) NULL
• whatsapp_enabled BOOLEAN NOT NULL DEFAULT false
• whatsapp_number VARCHAR(255) NULL
• created_at TIMESTAMP NULL
• updated_at TIMESTAMP NULL

TABLE: shop_social_links
Description: Social and marketplace profile links.

Columns: • id BIGINT UNSIGNED PRIMARY KEY NOT NULL
• facebook VARCHAR(255) NULL
• instagram VARCHAR(255) NULL
• linkedin VARCHAR(255) NULL
• youtube VARCHAR(255) NULL
• tiktok VARCHAR(255) NULL
• discord VARCHAR(255) NULL
• telegram VARCHAR(255) NULL
• daraz VARCHAR(255) NULL
• amazon VARCHAR(255) NULL
• walmart VARCHAR(255) NULL
• created_at TIMESTAMP NULL
• updated_at TIMESTAMP NULL

TABLE: shop_sms_settings
Description: SMS provider credentials and OTP-on-order toggle.

Columns: • id BIGINT UNSIGNED PRIMARY KEY NOT NULL
• provider VARCHAR(255) NOT NULL DEFAULT 'bulksmsbd'
• api_key VARCHAR(255) NULL
• sender_id VARCHAR(255) NULL
• verify_phone_on_order BOOLEAN NOT NULL DEFAULT false
• created_at TIMESTAMP NULL
• updated_at TIMESTAMP NULL

TABLE: shop_sms_templates
Description: Order-status SMS message templates.

Columns: • id BIGINT UNSIGNED PRIMARY KEY NOT NULL
• key VARCHAR(255) NOT NULL UNIQUE
• title VARCHAR(255) NOT NULL
• body TEXT NOT NULL
• status VARCHAR(20) NOT NULL DEFAULT 'active'
• sort_order SMALLINT UNSIGNED NOT NULL DEFAULT 0
• created_at TIMESTAMP NULL
• updated_at TIMESTAMP NULL

Template keys:
payment_failed, order_completed, order_delivered, order_shipped, order_confirmed, on_hold, order_placed

TABLE: shop_marketing_settings
Description: Marketing pixels (Facebook Pixel).

Columns: • id BIGINT UNSIGNED PRIMARY KEY NOT NULL
• facebook_pixel_id VARCHAR(255) NULL
• facebook_pixel_enabled BOOLEAN NOT NULL DEFAULT false
• created_at TIMESTAMP NULL
• updated_at TIMESTAMP NULL

TABLE: receipt_counters
Description: Counter used to mint 9-digit receipt tokens.

Columns: • id BIGINT UNSIGNED PRIMARY KEY NOT NULL
• num1 BIGINT UNSIGNED NOT NULL DEFAULT 111
• num2 BIGINT UNSIGNED NOT NULL DEFAULT 222
• num3 BIGINT UNSIGNED NOT NULL DEFAULT 333
• created_at TIMESTAMP NULL
• updated_at TIMESTAMP NULL

RELATIONSHIPS:

• products.category_id → categories.id
• product_images.product_id → products.id
• product_variants.product_id → products.id
• product_variant_options.product_variant_id → product_variants.id
• product_details.product_id → products.id
• order_items.order_id → orders.id
• order_items.product_id → products.id
• sessions.user_id → users.id (index only)

BUSINESS DEFINITIONS:

• "active product" means products.status = 'active'
• "draft product" means products.status = 'draft'
• "archived product" means products.status = 'archived'
• "active category" means categories.status = 'active'
• "inside Dhaka delivery" means orders.delivery_area = 'inside'
• "outside Dhaka delivery" means orders.delivery_area = 'outside'
• "COD" means orders.payment_method = 'cod'
• "online order" means orders.order_type = 'online'
• "in-shop / POS order" means orders.order_type = 'in_shop'
• "revenue" means SUM(orders.total) where status IN ('confirmed','shipped','delivered','completed')
• "stock deducted orders" means orders with status IN ('confirmed','shipped','delivered','completed') and stock_adjusted = true
• "promo amount discount" means promo_codes.discount_type = 'amount'
• "promo percentage discount" means promo_codes.discount_type = 'percentage'

Notes: • customers table existed briefly and was dropped — not in final schema.
• Dropped product columns: default_shipping, weight, weight_unit, length, width, height, condition.
• No separate payment_status column — payment state is tracked via status + paid_amount.
• Total tables: 25
"""


class PromptGenerator:
    SCHEMA_MAX_AGE = timedelta(days=7)

    def generate(
        self,
        question: str,
        conversation_context: str = "",
    ) -> str:
        # schema = self._get_schema()
        schema = multi_tenent_schema

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
You are a SQL generation engine.

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
