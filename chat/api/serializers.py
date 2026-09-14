from rest_framework import serializers


class AccessRequestSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="")


class ProfileSerializer(serializers.Serializer):
    industry = serializers.CharField(required=False, allow_blank=True, default="")
    business = serializers.CharField(required=False, allow_blank=True, default="")
    keeps = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
    )


class DiscoverIngestSerializer(serializers.Serializer):
    rows = serializers.ListField(required=True)


class AccessAllowListSerializer(serializers.Serializer):
    allowed_tables = serializers.ListField(
        child=serializers.CharField(),
        required=True,
    )
    allowed_columns = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField()),
        required=True,
    )


class MessageCreateSerializer(serializers.Serializer):
    content = serializers.CharField(required=True, allow_blank=False, trim_whitespace=True)


class MessageResultSerializer(serializers.Serializer):
    user_message_id = serializers.IntegerField(required=True)
    rows = serializers.ListField(
        child=serializers.DictField(),
        required=False,
    )
    result = serializers.ListField(
        child=serializers.DictField(),
        required=False,
    )

    def validate(self, attrs):
        rows = attrs.get("rows")
        if rows is None:
            rows = attrs.get("result")
        if rows is None:
            raise serializers.ValidationError({"rows": "This field is required."})
        attrs["rows"] = rows
        return attrs


class ChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
    )


class ChatRequestResultSerializer(serializers.Serializer):
    user_message_id = serializers.IntegerField(required=True)
    result = serializers.ListField(
        child=serializers.DictField(),
        required=True,
    )
