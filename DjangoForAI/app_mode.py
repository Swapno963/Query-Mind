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


def allowed_product_modes(*, chat: bool, api: bool) -> tuple[str, ...]:
    if chat and api:
        return VALID_MODES
    if chat:
        return ("chat",)
    if api:
        return ("api",)
    return ()


def resolve_signup_product(requested: str | None, *, chat: bool, api: bool) -> str:
    allowed = allowed_product_modes(chat=chat, api=api)
    if len(allowed) == 1:
        return allowed[0]
    product = (requested or "chat").strip().lower()
    if product not in allowed:
        return "chat" if "chat" in allowed else (allowed[0] if allowed else "chat")
    return product
