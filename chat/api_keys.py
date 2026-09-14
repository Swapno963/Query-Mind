from __future__ import annotations

import hashlib
import secrets

from chat.models import ApiAccessRequest, ApiKey


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    token = secrets.token_urlsafe(32)
    raw = f"qm_live_{token}"
    prefix = raw[:16]
    return raw, prefix, hash_api_key(raw)


def user_has_approved_api_access(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    return ApiAccessRequest.objects.filter(
        user=user,
        status=ApiAccessRequest.STATUS_APPROVED,
    ).exists()


def lookup_api_key(raw: str) -> ApiKey | None:
    if not raw:
        return None
    key = ApiKey.objects.filter(key_hash=hash_api_key(raw), revoked_at__isnull=True).select_related("user").first()
    if key is None:
        return None
    if not user_has_approved_api_access(key.user):
        return None
    return key
