from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..services import ConversationService
from chat.api.chat_service import ChatService

from .serializers import ChatRequestSerializer, ChatRequestResultSerializer


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

        return Response(
            {
                # "conversation_id": conversation.id,
                "user_id": conversation.user_id,
                "tenant_id": conversation.tenant_id,
                "user_message_id": user_message.id,
                # "ai_message_id": ai_message.id,
                "sql": result["sql"],
                # "rows": result["rows"],
                # "answer": result["answer"],
                "conversation_created": created,
                # "timestamp": ai_message.timestamp,
            },
            status=status.HTTP_200_OK,
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
