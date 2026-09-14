from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from chat.api_keys import lookup_api_key


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
