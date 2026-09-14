from rest_framework.permissions import BasePermission

from chat.models import ApiKey


class IsApiKeyAuthenticated(BasePermission):
    message = "This endpoint requires an approved QueryMind API key."

    def has_permission(self, request, view):
        return isinstance(getattr(request, "auth", None), ApiKey)
