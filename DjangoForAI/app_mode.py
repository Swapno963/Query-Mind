"""Deployment APP_MODE (chat UI, REST API, or both) vs org product (chat, api, mcp)."""

from django.core.exceptions import ImproperlyConfigured

VALID_MODES = ("chat", "api", "both")
ALIASES = {
    "chat-only": "chat",
    "api-only": "api",
    "all": "both",
}

PRODUCT_CHAT = "chat"
PRODUCT_API = "api"
PRODUCT_MCP = "mcp"
PRODUCT_BOTH = "both"
PRODUCT_MODES = (PRODUCT_CHAT, PRODUCT_API, PRODUCT_MCP)
PRODUCT_ALIASES = {
    "both": PRODUCT_MCP,
    "all": PRODUCT_MCP,
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
    modes: list[str] = []
    if chat:
        modes.append(PRODUCT_CHAT)
    if api:
        modes.append(PRODUCT_API)
        modes.append(PRODUCT_MCP)
    return tuple(modes)


def resolve_signup_product(requested: str | None, *, chat: bool, api: bool) -> str:
    allowed = allowed_product_modes(chat=chat, api=api)
    product = (requested or "").strip().lower()
    product = PRODUCT_ALIASES.get(product, product)
    if product in allowed:
        return product
    if PRODUCT_CHAT in allowed:
        return PRODUCT_CHAT
    return allowed[0] if allowed else PRODUCT_CHAT
