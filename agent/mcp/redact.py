from __future__ import annotations

from typing import Any

SECRET_KEY_PARTS = ("password", "token", "secret", "authorization", "api_key", "apikey")


def is_secret_key(key: str) -> bool:
    lowered = str(key or "").lower().replace("-", "_")
    return any(part in lowered for part in SECRET_KEY_PARTS)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[redacted]" if is_secret_key(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value
