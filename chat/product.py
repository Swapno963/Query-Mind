"""Organization product choice, constrained by deployment APP_MODE."""

from __future__ import annotations

from django.conf import settings

from DjangoForAI.app_mode import allowed_product_modes, resolve_signup_product
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
    if mode in {"chat", "api", "both"}:
        return clamp_product_mode(mode)
    if settings.CHAT_ENABLED and settings.API_ENABLED:
        return ""
    return clamp_product_mode(None)


def org_chat_enabled(org) -> bool:
    if not settings.CHAT_ENABLED:
        return False
    mode = org_product_mode(org)
    if not mode:
        return False
    return mode in {"chat", "both"}


def org_api_enabled(org) -> bool:
    if not settings.API_ENABLED:
        return False
    mode = org_product_mode(org)
    if not mode:
        return False
    return mode in {"api", "both"}


def org_llm_backend(org) -> str:
    value = clamp_llm_backend(getattr(org, "llm_backend", None))
    return value or "local"


def home_url_name(org) -> str:
    if org_chat_enabled(org):
        return "ask"
    if org_api_enabled(org):
        return "developers"
    return "ask" if settings.CHAT_ENABLED else "developers"


def selectable_products() -> tuple[str, ...]:
    return allowed_product_modes(chat=settings.CHAT_ENABLED, api=settings.API_ENABLED)


def apply_product_mode(org, requested: str | None) -> str:
    mode = clamp_product_mode(requested)
    org.product_mode = mode
    if mode == "api":
        org.llm_backend = ""
        org.save(update_fields=["product_mode", "llm_backend"])
    else:
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
    """Return 'product', 'chat', 'api', or None when setup is complete."""
    if org is None:
        return "product"
    mode = org_product_mode(org)
    if settings.CHAT_ENABLED and settings.API_ENABLED and not mode:
        return "product"
    if not mode:
        mode = clamp_product_mode(None)
    chat_on = settings.CHAT_ENABLED and mode in {"chat", "both"}
    api_on = settings.API_ENABLED and mode in {"api", "both"}
    if chat_on:
        if clamp_llm_backend(org.llm_backend) not in VALID_LLM:
            return "chat"
        if not _live_db_ready(_workspace(org, KIND_CHAT)):
            return "chat"
    if api_on and not _live_db_ready(_workspace(org, KIND_API)):
        return "api"
    return None
