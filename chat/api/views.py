from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.http import JsonResponse

from agent.graph import build_api_query_graph
from agent.state import QueryMindState
from chat.api.chat_service import ChatService, build_chat_response
from chat.api.serializers import ChatRequestSerializer, ChatRequestResultSerializer
from chat.services import ConversationService
from chat.ui import workspace_for


def health_check(request):
    return JsonResponse({"status": "ok", "version": "1.0.0"})


class ChatAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message_content = serializer.validated_data["message"]
        conversation, created = ConversationService.get_or_create_conversation(
            user=request.user,
        )
        user_message = ConversationService.add_user_message(
            conversation,
            message_content,
        )
        result = ChatService.process_message(
            conversation=conversation,
            user_message=user_message,
        )
        return build_chat_response(
            conversation=conversation,
            user_message=user_message,
            result=result,
            created=created,
        )


class ChatResultAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChatRequestResultSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_message_id = serializer.validated_data["user_message_id"]
        result = serializer.validated_data["result"]
        conversation, created = ConversationService.get_or_create_conversation(
            user=request.user,
        )
        content = ConversationService.get_user_message_content(
            user_message_id=user_message_id
        )
        result = ChatService.process_Result(
            conversation=conversation,
            user_message=content,
            result=result,
        )
        return Response(
            {
                "user_id": request.user.id,
                "answer": result["answer"],
                "conversation_created": created,
            },
            status=status.HTTP_200_OK,
        )


class ChatAPIView_GRAPH(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message_content = serializer.validated_data["message"]
        workspace = workspace_for(request.user)
        if not workspace or not workspace.allowed_tables:
            return Response(
                {
                    "error": {
                        "code": "NO_ALLOW_LIST",
                        "details": "Choose allowed tables before asking.",
                    },
                    "sql": None,
                    "is_executable": False,
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        conversation, created = ConversationService.get_or_create_conversation(
            user=request.user,
        )
        user_message = ConversationService.add_user_message(
            conversation,
            message_content,
        )
        state = QueryMindState(
            question=message_content,
            conversation_id=conversation.id,
            message_id=user_message.id,
            connection_id=workspace.pk,
            workspace_id=workspace.pk,
            allowed_tables=list(workspace.allowed_tables or []),
            schema_text=workspace.schema_text or "",
        )
        final_state = build_api_query_graph().invoke(state)
        return Response(
            {
                "user_id": request.user.id,
                "user_message_id": user_message.id,
                "sql": final_state.get("sql") if (final_state.get("validation_result") or {}).get("valid") else None,
                "is_executable": bool(
                    (final_state.get("validation_result") or {}).get("valid")
                ),
                "conversation_created": created,
            },
            status=status.HTTP_200_OK,
        )
