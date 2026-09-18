from rest_framework.permissions import BasePermission

from chat.models import ApiKey
from chat.organizations import organization_for
from chat.product import org_api_enabled


class IsApiKeyAuthenticated(BasePermission):
    message = "This endpoint requires an approved QueryMind API key."

    def has_permission(self, request, view):
        if not isinstance(getattr(request, "auth", None), ApiKey):
            return False
        return org_api_enabled(organization_for(request.user))
