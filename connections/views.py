from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from chat.ui import KIND_CHAT, chat_ready, workspace_for
from connections.services.schema_discovery import filter_schema_to_tables


class QueryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        workspace = workspace_for(request.user, KIND_CHAT)
        if not chat_ready(workspace):
            return Response(
                {
                    "success": False,
                    "error": "Connect PostgreSQL and choose allowed tables and columns first.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        schema = filter_schema_to_tables(
            workspace.schema_text or "",
            workspace.allowed_tables,
            workspace.allowed_columns,
        )
        return Response(
            {
                "success": True,
                "llm_schema": schema,
                "allowed_tables": workspace.allowed_tables,
                "allowed_columns": workspace.allowed_columns,
            },
            status=status.HTTP_200_OK,
        )
