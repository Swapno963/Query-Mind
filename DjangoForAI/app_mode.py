"""Deployment product mode: chat UI, REST API, or both."""

from django.core.exceptions import ImproperlyConfigured

VALID_MODES = ("chat", "api", "both")
ALIASES = {
    "chat-only": "chat",
    "api-only": "api",
    "all": "both",
}


def parse_app_mode(raw: str | None) -> str:
    value = (raw or "both").strip().lower()
    value = ALIASES.get(value, value)
    if value not in VALID_MODES:
        raise ImproperlyConfigured(
            f"APP_MODE must be one of {', '.join(VALID_MODES)} (got {raw!r})."
        )
    return value


def chat_enabled(mode: str) -> bool:
    return mode in {"chat", "both"}


def api_enabled(mode: str) -> bool:
    return mode in {"api", "both"}


def resolve_signup_product(requested: str | None, *, chat: bool, api: bool) -> str:
    if chat and not api:
        return "chat"
    if api and not chat:
        return "api"
    product = (requested or "chat").strip().lower()
    if product not in {"chat", "api"}:
        return "chat"
    return product
