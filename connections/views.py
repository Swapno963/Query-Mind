from connections.services.schema_discovery import PostgreSQLSchemaDiscovery
from rest_framework.views import APIView
from connections.models import DatabaseSchema


class QueryView(APIView):

    def post(self, request):
        discovery = PostgreSQLSchemaDiscovery()

        schema = discovery.discover()

        # Generate SQL...
