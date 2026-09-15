from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from agent.graph import build_api_query_graph
from agent.state import QueryMindState
from chat.api.chat_service import ChatService
from chat.api.errors import api_error
from chat.api.serializers import (
    AccessAllowListSerializer,
    AccessRequestSerializer,
    ChatRequestResultSerializer,
    ChatRequestSerializer,
    DiscoverIngestSerializer,
    MessageCreateSerializer,
    MessageResultSerializer,
    ProfileSerializer,
)
from chat.api_keys import generate_api_key, user_has_approved_api_access
from chat.models import ApiAccessRequest, ApiKey, Conversation, Message
from chat.permissions import IsApiKeyAuthenticated
from chat.services import ConversationService
from chat.ui import KIND_API, api_ready, get_or_create_workspace as create_workspace
from connections.models import WorkspaceConnection
from connections.services.catalog import (
    DISCOVERY_SQL,
    catalog_from_discovery_rows,
    intersect_allow_lists,
    schema_text_from_catalog,
)
from connections.services.schema_discovery import filter_schema_to_tables


def get_or_create_workspace(user) -> WorkspaceConnection:
    return create_workspace(user, KIND_API)


def workspace_payload(workspace: WorkspaceConnection) -> dict:
    return {
        "kind": workspace.kind,
        "industry": workspace.industry,
        "business": workspace.business,
        "keeps": workspace.keeps or [],
        "discovered_tables": workspace.discovered_tables or [],
        "discovered_columns": workspace.discovered_columns or {},
        "allowed_tables": workspace.allowed_tables or [],
        "allowed_columns": workspace.allowed_columns or {},
        "ready": api_ready(workspace),
    }


class AccessRequestView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        latest = request.user.api_access_requests.order_by("-created_at").first()
        return Response(
            {
                "status": latest.status if latest else "none",
                "approved": user_has_approved_api_access(request.user),
            }
        )

    def post(self, request):
        serializer = AccessRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if user_has_approved_api_access(request.user):
            return Response({"status": ApiAccessRequest.STATUS_APPROVED, "approved": True})
        pending = request.user.api_access_requests.filter(
            status=ApiAccessRequest.STATUS_PENDING
        ).first()
        if pending:
            return Response({"id": pending.id, "status": pending.status}, status=status.HTTP_200_OK)
        created = ApiAccessRequest.objects.create(
            user=request.user,
            note=serializer.validated_data.get("note") or "",
        )
        return Response(
            {"id": created.id, "status": created.status},
            status=status.HTTP_201_CREATED,
        )


class ApiKeyCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not user_has_approved_api_access(request.user):
            return api_error(
                "permission_error",
                "Your API access request has not been approved yet.",
                403,
            )
        raw, prefix, hashed = generate_api_key()
        ApiKey.objects.create(user=request.user, prefix=prefix, key_hash=hashed)
        return Response(
            {
                "key": raw,
                "prefix": prefix,
                "warning": "Store this key now. QueryMind will not show it again.",
            },
            status=status.HTTP_201_CREATED,
        )


class ProfileView(APIView):
    permission_classes = [IsApiKeyAuthenticated]

    def put(self, request):
        serializer = ProfileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        workspace = get_or_create_workspace(request.user)
        workspace.industry = serializer.validated_data.get("industry") or ""
        workspace.business = serializer.validated_data.get("business") or ""
        workspace.keeps = serializer.validated_data.get("keeps") or []
        workspace.save(update_fields=["industry", "business", "keeps", "updated_at"])
        return Response(workspace_payload(workspace))


class DiscoverInstructionsView(APIView):
    permission_classes = [IsApiKeyAuthenticated]

    def get(self, request):
        return Response(
            {
                "dialect": "postgres",
                "sql": DISCOVERY_SQL,
                "instructions": (
                    "Run this read-only SQL on your PostgreSQL database, then POST the rows "
                    "to /api/v1/discover."
                ),
            }
        )


class DiscoverIngestView(APIView):
    permission_classes = [IsApiKeyAuthenticated]

    def post(self, request):
        serializer = DiscoverIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        catalog = catalog_from_discovery_rows(serializer.validated_data["rows"])
        if not catalog["tables"]:
            return api_error(
                "invalid_request_error",
                "No tables were found in the discovery rows. Each row needs table_name and column_name.",
            )
        workspace = get_or_create_workspace(request.user)
        workspace.discovered_tables = catalog["tables"]
        workspace.discovered_columns = catalog["columns"]
        workspace.schema_text = schema_text_from_catalog(
            catalog["tables"],
            catalog["columns"],
        )
        workspace.save(
            update_fields=[
                "discovered_tables",
                "discovered_columns",
                "schema_text",
                "updated_at",
            ]
        )
        return Response(
            {
                "tables": catalog["tables"],
                "columns": catalog["columns"],
            }
        )


class AccessAllowListView(APIView):
    permission_classes = [IsApiKeyAuthenticated]

    def put(self, request):
        serializer = AccessAllowListSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        workspace = get_or_create_workspace(request.user)
        if not workspace.discovered_tables:
            return api_error(
                "invalid_request_error",
                "Run discovery first and POST the SQL results to /api/v1/discover.",
            )
        allowed_tables, allowed_columns = intersect_allow_lists(
            requested_tables=serializer.validated_data["allowed_tables"],
            requested_columns=serializer.validated_data["allowed_columns"],
            discovered_tables=workspace.discovered_tables or [],
            discovered_columns=workspace.discovered_columns or {},
        )
        if not allowed_tables:
            return api_error(
                "invalid_request_error",
                "Choose at least one discovered table and column. Invented names are ignored.",
            )
        workspace.allowed_tables = allowed_tables
        workspace.allowed_columns = allowed_columns
        workspace.schema_text = filter_schema_to_tables(
            workspace.schema_text or schema_text_from_catalog(
                workspace.discovered_tables,
                workspace.discovered_columns,
            ),
            allowed_tables,
            allowed_columns,
        )
        workspace.save(
            update_fields=[
                "allowed_tables",
                "allowed_columns",
                "schema_text",
                "updated_at",
            ]
        )
        return Response(workspace_payload(workspace))


class WorkspaceView(APIView):
    permission_classes = [IsApiKeyAuthenticated]

    def get(self, request):
        workspace = get_or_create_workspace(request.user)
        return Response(workspace_payload(workspace))


def _run_sql_generation(user, content: str):
    workspace = get_or_create_workspace(user)
    if not api_ready(workspace):
        return None, api_error(
            "permission_error",
            "Choose allowed tables and columns before asking.",
            403,
        )
    conversation, created = ConversationService.get_or_create_conversation(
        user=user,
        workspace=workspace,
    )
    if created or conversation.title == "New Chat":
        conversation.title = content[:50] + ("..." if len(content) > 50 else "")
        conversation.save(update_fields=["title", "updated_at"])
    user_message = ConversationService.add_user_message(conversation, content)
    state = QueryMindState(
        question=content,
        conversation_id=conversation.id,
        message_id=user_message.id,
        connection_id=workspace.pk,
        workspace_id=workspace.pk,
        allowed_tables=list(workspace.allowed_tables or []),
        allowed_columns=dict(workspace.allowed_columns or {}),
        schema_text=workspace.schema_text or "",
    )
    final_state = build_api_query_graph().invoke(state)
    validation = final_state.get("validation_result") or {}
    executable = bool(validation.get("valid"))
    sql = final_state.get("sql") if executable else None
    kind = validation.get("kind") or ("ok" if executable else "unavailable")
    stop_reason = "sql" if executable else "refusal"
    payload = {
        "id": f"msg_{user_message.id}",
        "type": "message",
        "role": "assistant",
        "stop_reason": stop_reason,
        "user_message_id": user_message.id,
        "conversation_id": conversation.id,
        "conversation_created": created,
        "content": (
            [{"type": "sql", "sql": sql, "executable": True}]
            if executable
            else [
                {
                    "type": "text",
                    "text": validation.get("error")
                    or "QueryMind could not read that from your allowed tables and columns.",
                }
            ]
        ),
    }
    if not executable:
        payload["error"] = {
            "type": kind,
            "message": validation.get("error") or "SQL was not executable.",
        }
    return payload, None


class MessagesView(APIView):
    permission_classes = [IsApiKeyAuthenticated]

    def post(self, request):
        serializer = MessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload, error = _run_sql_generation(
            request.user,
            serializer.validated_data["content"],
        )
        if error:
            return error
        return Response(payload, status=status.HTTP_200_OK)


class MessageResultsView(APIView):
    permission_classes = [IsApiKeyAuthenticated]

    def post(self, request):
        serializer = MessageResultSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not api_ready(get_or_create_workspace(request.user)):
            return api_error(
                "permission_error",
                "Choose allowed tables and columns before asking.",
                403,
            )
        user_message_id = serializer.validated_data["user_message_id"]
        try:
            user_message = Message.objects.select_related("conversation").get(
                id=user_message_id,
                is_user=True,
                conversation__user=request.user,
            )
        except Message.DoesNotExist:
            return api_error("not_found_error", "That user message was not found.", 404)
        result = ChatService.process_Result(
            conversation=user_message.conversation,
            user_message=user_message.content,
            result=serializer.validated_data["rows"],
        )
        answer = (result.get("answer") or "").strip() or (
            "No matching records in the tables you allowed."
        )
        ai_message = ConversationService.add_ai_message(
            user_message.conversation,
            answer,
        )
        return Response(
            {
                "id": f"msg_{ai_message.id}",
                "type": "message",
                "role": "assistant",
                "stop_reason": "end_turn",
                "user_message_id": user_message.id,
                "conversation_id": user_message.conversation_id,
                "content": [{"type": "text", "text": answer}],
            }
        )


class ChatAPIView(APIView):
    permission_classes = [IsApiKeyAuthenticated]

    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload, error = _run_sql_generation(
            request.user,
            serializer.validated_data["message"],
        )
        if error:
            return error
        return Response(payload)


class ChatResultAPIView(MessageResultsView):
    pass


class ChatAPIView_GRAPH(ChatAPIView):
    pass
