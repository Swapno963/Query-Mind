"""Organization product choice, constrained by deployment APP_MODE."""

from __future__ import annotations

from django.conf import settings

from DjangoForAI.app_mode import (
    PRODUCT_API,
    PRODUCT_BOTH,
    PRODUCT_CHAT,
    PRODUCT_MCP,
    PRODUCT_MODES,
    allowed_product_modes,
    resolve_signup_product,
)
from connections.models import WorkspaceConnection

KIND_CHAT = WorkspaceConnection.KIND_CHAT
KIND_API = WorkspaceConnection.KIND_API


def _live_db_ready(workspace) -> bool:
    return bool(
        workspace
        and workspace.host
        and workspace.db_name
        and workspace.allowed_tables
        and workspace.allowed_columns
    )


VALID_LLM = ("local", "online")


def clamp_product_mode(requested: str | None) -> str:
    return resolve_signup_product(
        requested,
        chat=settings.CHAT_ENABLED,
        api=settings.API_ENABLED,
    )


def clamp_llm_backend(requested: str | None) -> str:
    value = (requested or "").strip().lower()
    if value in VALID_LLM:
        return value
    return ""


def org_product_mode(org) -> str:
    mode = (getattr(org, "product_mode", None) or "").strip().lower()
    if mode == PRODUCT_BOTH:
        return PRODUCT_BOTH
    if mode in PRODUCT_MODES:
        return mode
    if len(selectable_products()) > 1:
        return ""
    return clamp_product_mode(None)


def org_chat_enabled(org) -> bool:
    if not settings.CHAT_ENABLED:
        return False
    mode = org_product_mode(org)
    if not mode:
        return False
    return mode in {PRODUCT_CHAT, PRODUCT_BOTH}


def org_api_enabled(org) -> bool:
    if not settings.API_ENABLED:
        return False
    mode = org_product_mode(org)
    if not mode:
        return False
    return mode in {PRODUCT_API, PRODUCT_BOTH}


def org_mcp_enabled(org) -> bool:
    if not settings.API_ENABLED:
        return False
    mode = org_product_mode(org)
    if not mode:
        return False
    return mode == PRODUCT_MCP


def org_keys_enabled(org) -> bool:
    return org_api_enabled(org) or org_mcp_enabled(org)


def key_kind_for_org(org) -> str:
    return PRODUCT_MCP if org_mcp_enabled(org) else PRODUCT_API


def org_llm_backend(org) -> str:
    value = clamp_llm_backend(getattr(org, "llm_backend", None))
    return value or "local"


def home_url_name(org) -> str:
    if next_setup_step(org) == "product":
        return "onboarding"
    if org_chat_enabled(org):
        return "ask"
    if org_api_enabled(org):
        return "developers"
    if org_mcp_enabled(org):
        return "mcp_docs"
    return "ask" if settings.CHAT_ENABLED else "developers"


def selectable_products() -> tuple[str, ...]:
    return allowed_product_modes(chat=settings.CHAT_ENABLED, api=settings.API_ENABLED)


def apply_product_mode(org, requested: str | None) -> str:
    mode = clamp_product_mode(requested)
    org.product_mode = mode
    org.save(update_fields=["product_mode"])
    return mode


def apply_llm_backend(org, requested: str | None) -> str:
    backend = clamp_llm_backend(requested) or "local"
    org.llm_backend = backend
    org.save(update_fields=["llm_backend"])
    return backend


def _workspace(org, kind: str):
    if not org:
        return None
    return WorkspaceConnection.objects.filter(organization=org, kind=kind).first()


def next_setup_step(org) -> str | None:
    """Return 'product', 'chat', 'api', 'mcp', or None when setup is complete."""
    if org is None:
        return "product"
    mode = org_product_mode(org)
    if not mode:
        if len(selectable_products()) > 1:
            return "product"
        mode = clamp_product_mode(None)
    chat_on = settings.CHAT_ENABLED and mode in {PRODUCT_CHAT, PRODUCT_BOTH}
    api_on = settings.API_ENABLED and mode in {PRODUCT_API, PRODUCT_BOTH}
    mcp_on = settings.API_ENABLED and mode == PRODUCT_MCP
    if chat_on:
        if clamp_llm_backend(org.llm_backend) not in VALID_LLM:
            return "chat"
        if not _live_db_ready(_workspace(org, KIND_CHAT)):
            return "chat"
    if api_on and not _live_db_ready(_workspace(org, KIND_API)):
        return "api"
    if mcp_on:
        if clamp_llm_backend(org.llm_backend) not in VALID_LLM:
            return "mcp"
        if not (getattr(org, "mcp_server_url", None) or "").strip():
            return "mcp"
    return None
