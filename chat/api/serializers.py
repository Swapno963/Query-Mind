from rest_framework import serializers


class ChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
    )


from rest_framework import serializers


class ChatRequestSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(
        required=True,
    )

    tenant_id = serializers.IntegerField(
        required=True,
    )

    message = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
    )


class ChatResponseSerializer(serializers.Serializer):
    conversation_id = serializers.IntegerField()
    user_message_id = serializers.IntegerField()
    ai_message_id = serializers.IntegerField()
    content = serializers.CharField()
    timestamp = serializers.DateTimeField()
