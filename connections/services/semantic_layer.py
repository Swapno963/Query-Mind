from __future__ import annotations

from typing import Any


DEMO_TABLES = {"users", "products", "orders", "order_items"}

DEMO_SEMANTIC_LAYER: dict[str, Any] = {
    "tables": {
        "users": {"description": "Application users."},
        "products": {"description": "Products available for sale."},
        "orders": {
            "description": "Customer purchase orders. Grain: one row per order.",
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
                    "values": ["UNPAID", "PAID", "REFUNDED"],
                },
            },
        },
        "order_items": {
            "description": "Line items on an order. Grain: one row per item. Joining this to orders fans out orders."
        },
    },
    "business_definitions": [
        '"unpaid" means orders.payment_status = \'UNPAID\'',
        '"paid" means orders.payment_status = \'PAID\'',
        '"revenue" means SUM(orders.total_amount) WHERE orders.payment_status = \'PAID\'',
        "Do not SUM(orders.total_amount) after joining order_items; that duplicates orders.",
    ],
    "metrics": {
        "revenue": {
            "expr": "SUM(orders.total_amount)",
            "table": "orders",
            "grain": "order",
            "filters": [
                {
                    "column": "orders.payment_status",
                    "op": "eq",
                    "value": "PAID",
                }
            ],
        }
    },
    "aliases": {
        "paid": {"column": "orders.payment_status", "value": "PAID"},
        "unpaid": {"column": "orders.payment_status", "value": "UNPAID"},
        "refunded": {"column": "orders.payment_status", "value": "REFUNDED"},
    },
}


def merge_semantic_layer(
    discovered_tables: list[str],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = dict(existing or {})
    names = {str(name).lower() for name in discovered_tables}
    if DEMO_TABLES.issubset(names):
        for key, value in DEMO_SEMANTIC_LAYER.items():
            if key not in merged or not merged[key]:
                merged[key] = value
            elif isinstance(value, dict) and isinstance(merged.get(key), dict):
                combined = dict(value)
                combined.update(merged[key])
                merged[key] = combined
    return merged
