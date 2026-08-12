from connections.services.schema_discovery import PostgreSQLSchemaDiscovery
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from connections.services.schema_discovery import transform_schema_for_llm

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
    "rules": [
        "Only use tables and columns listed above.",
        "Never invent columns.",
        "Use foreign-key relationships for JOINs.",
        "Return PostgreSQL SQL only.",
    ],
}


class QueryView(APIView):

    def get(self, request):
        discovery = PostgreSQLSchemaDiscovery()

        schema = discovery.discover()
        llm_schema = transform_schema_for_llm(
            schema,
            semantic_config,
        )

        # print(llm_schema)
        return Response(
            {
                "success": True,
                "llm_schema": llm_schema,
            },
            status=status.HTTP_200_OK,
        )
