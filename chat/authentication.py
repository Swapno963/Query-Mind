from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from chat.api_keys import lookup_api_key
from chat.organizations import organization_for


def mcp_headers_from_request(request) -> dict[str, str]:
    token = (
        request.headers.get("X-MCP-Authorization")
        or request.headers.get("x-mcp-authorization")
        or ""
    )
    if not token:
        return {}
    if not token.lower().startswith("bearer "):
        token = f"Bearer {token}"
    return {"Authorization": token}


def mcp_headers_for_user(user, request=None) -> dict[str, str]:
    if request is not None:
        headers = mcp_headers_from_request(request)
        if headers:
            return headers
    org = organization_for(user) if user else None
    token = org.get_mcp_access_token() if org else ""
    if not token:
        return {}
    if not token.lower().startswith("bearer "):
        token = f"Bearer {token}"
    return {"Authorization": token}


class ApiKeyAuthentication(BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        raw = request.headers.get("x-api-key") or ""
        if not raw:
            header = request.headers.get("Authorization") or ""
            if header.startswith(f"{self.keyword} "):
                raw = header[len(self.keyword) + 1 :].strip()
        if not raw:
            return None
        key = lookup_api_key(raw)
        if key is None:
            raise AuthenticationFailed("Invalid API key.")
        request.api_key = key
        return (key.user, key)
