from connections.services.schema_discovery import PostgreSQLSchemaDiscovery
from rest_framework.views import APIView
from connections.models import DatabaseSchema
from rest_framework.response import Response
from rest_framework import status


class QueryView(APIView):

    def get(self, request):
        discovery = PostgreSQLSchemaDiscovery()

        schema = discovery.discover()
        return Response(
            {
                "success": True,
                "schema": schema,
            },
            status=status.HTTP_200_OK,
        )

        # Generate SQL...
