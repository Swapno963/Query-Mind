from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..services import ConversationService
from chat.api.chat_service import ChatService

from .serializers import ChatRequestSerializer, ChatRequestResultSerializer
from django.http import JsonResponse
from chat.api.chat_service import build_chat_response
from agent.state import QueryMindState
from agent.graph import build_api_query_graph


def health_check(request):
    return JsonResponse({"status": "ok", "version": "1.0.0"})


class ChatAPIView(APIView):

    def post(self, request):

        # -----------------------------------------
        # 1. Validate request
        # -----------------------------------------

        serializer = ChatRequestSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        user_id = serializer.validated_data["user_id"]
        tenant_id = serializer.validated_data["tenant_id"]
        message_content = serializer.validated_data["message"]

        # -----------------------------------------
        # 2. Get or create conversation
        # -----------------------------------------

        conversation, created = ConversationService.get_or_create_conversation(
            user_id=user_id,
            tenant_id=tenant_id,
        )

        # -----------------------------------------
        # 3. Save user message
        # -----------------------------------------

        user_message = ConversationService.add_user_message(
            conversation,
            message_content,
        )

        # -----------------------------------------
        # 4. Run complete AI workflow
        # -----------------------------------------

        result = ChatService.process_message(
            conversation=conversation,
            user_message=user_message,
        )

        # ai_message = result["ai_message"]

        # -----------------------------------------
        # 5. Return complete response
        # -----------------------------------------

        # return Response(
        #     {
        #         "user_id": conversation.user_id,
        #         "tenant_id": conversation.tenant_id,
        #         "user_message_id": user_message.id,
        #         "sql": result["sql"],
        #         "conversation_created": created,
        #     },
        #     status=status.HTTP_200_OK,
        # )

        # 4. Return response using build_chat_response
        return build_chat_response(
            conversation=conversation,
            user_message=user_message,
            result=result,
            created=created,
        )


class ChatResultAPIView(APIView):

    def post(self, request):

        # -----------------------------------------
        # 1. Validate request
        # -----------------------------------------

        serializer = ChatRequestResultSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)

        user_id = serializer.validated_data["user_id"]
        tenant_id = serializer.validated_data["tenant_id"]
        user_message_id = serializer.validated_data["user_message_id"]
        result = serializer.validated_data["result"]

        # -----------------------------------------
        # 2. Get or create conversation
        # -----------------------------------------

        conversation, created = ConversationService.get_or_create_conversation(
            user_id=user_id,
            tenant_id=tenant_id,
        )

        # -----------------------------------------
        # 3. Save user message
        # -----------------------------------------
        content = ConversationService.get_user_message_content(
            user_message_id=user_message_id
        )
        # user_message = ConversationService.add_user_message(
        #     conversation,
        #     content,
        # )

        # add result prompt

        # -----------------------------------------
        # 4. Run complete AI workflow
        # -----------------------------------------

        result = ChatService.process_Result(
            conversation=conversation,
            user_message=content,
            result=result,
        )

        # ai_message = result["ai_message"]

        # -----------------------------------------
        # 5. Return complete response
        # -----------------------------------------

        return Response(
            {
                # "conversation_id": conversation.id,
                "user_id": conversation.user_id,
                "tenant_id": conversation.tenant_id,
                # "user_message_id": user_message.id,
                # "ai_message_id": ai_message.id,
                # "sql": result["sql"],
                # "rows": result["rows"],
                "answer": result["answer"],
                "conversation_created": created,
                # "timestamp": ai_message.timestamp,
            },
            status=status.HTTP_200_OK,
        )


class ChatAPIView_GRAPH(APIView):

    def post(self, request):

        # 1. Validate request
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user_id = serializer.validated_data["user_id"]
        tenant_id = serializer.validated_data["tenant_id"]
        message_content = serializer.validated_data["message"]

        # 2. Get or create conversation
        conversation, created = ConversationService.get_or_create_conversation(
            user_id=user_id,
            tenant_id=tenant_id,
        )

        # 3. Save user message
        user_message = ConversationService.add_user_message(
            conversation,
            message_content,
        )

        # 4. Create initial graph state
        state = QueryMindState(
            question=message_content,
            conversation_id=conversation.id,
            message_id=user_message.id,
            connection_id=0,
        )

        # 5. Run complete AI workflow
        final_state = build_api_query_graph().invoke(state)
        # print("The final state is : ", final_state)
        # 6. Return response
        return Response(
            {
                "user_id": conversation.user_id,
                "tenant_id": conversation.tenant_id,
                "user_message_id": user_message.id,
                "sql": final_state.get("sql"),
                # "answer": final_state.final_answer,
                "conversation_created": created,
            },
            status=status.HTTP_200_OK,
        )
