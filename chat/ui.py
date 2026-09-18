"""Shared template context for QueryMind product UI."""

from connections.models import WorkspaceConnection
from connections.services.engines import ENGINE_CHOICES, display_name
from chat.organizations import (
    active_membership,
    ensure_organization_for_user,
    is_org_admin,
    organization_for,
)
from chat.product import (
    home_url_name,
    next_setup_step,
    org_api_enabled,
    org_chat_enabled,
    org_llm_backend,
    org_product_mode,
    selectable_products,
)

from .constants import (
    AI_AVATAR_TEXT,
    AI_DISPLAY_NAME,
    EXAMPLE_QUESTIONS,
    RECENT_CONVERSATIONS_LIMIT,
)
from .models import Conversation

KIND_CHAT = WorkspaceConnection.KIND_CHAT
KIND_API = WorkspaceConnection.KIND_API

DEFAULT_PROFILE = {
    "source_name": "No data connected yet",
    "database": "",
    "business": "",
    "industry": "",
    "keeps": [],
    "tables": [],
    "updated_label": "",
    "is_readonly_role": False,
}


def workspace_for(user, kind=KIND_CHAT):
    if not user or not user.is_authenticated:
        return None
    org = organization_for(user)
    if org:
        shared = WorkspaceConnection.objects.filter(organization=org, kind=kind).first()
        if shared:
            return shared
    return WorkspaceConnection.objects.filter(user=user, kind=kind).first()


def get_or_create_workspace(user, kind):
    defaults = {
        "host": "",
        "port": 5432,
        "db_name": "",
        "db_user": "",
        "password_ciphertext": "",
    }
    org = organization_for(user) or ensure_organization_for_user(user)
    shared = WorkspaceConnection.objects.filter(organization=org, kind=kind).first()
    if shared:
        return shared
    if not is_org_admin(user):
        return None
    workspace, _created = WorkspaceConnection.objects.get_or_create(
        user=user,
        kind=kind,
        defaults={**defaults, "organization": org},
    )
    if workspace.organization_id is None:
        workspace.organization = org
        workspace.save(update_fields=["organization"])
    return workspace


def live_db_ready(workspace):
    return bool(
        workspace
        and workspace.host
        and workspace.db_name
        and workspace.allowed_tables
        and workspace.allowed_columns
    )


def chat_ready(workspace):
    return bool(
        workspace
        and workspace.kind == KIND_CHAT
        and live_db_ready(workspace)
    )


def api_db_ready(workspace):
    return bool(workspace and workspace.kind == KIND_API and live_db_ready(workspace))


def api_ready(workspace):
    return bool(
        workspace
        and workspace.kind == KIND_API
        and workspace.allowed_tables
        and workspace.allowed_columns
    )


def workspace_ready(workspace):
    if not workspace:
        return False
    if workspace.kind == KIND_API:
        return api_ready(workspace)
    return chat_ready(workspace)


def profile_from_workspace(workspace):
    if not workspace:
        return DEFAULT_PROFILE
    allowed = {str(name) for name in (workspace.allowed_tables or [])}
    allowed_columns = workspace.allowed_columns or {}
    tables = []
    for name in workspace.discovered_tables or []:
        cols = allowed_columns.get(name) or []
        tables.append(
            {
                "name": name,
                "description": (
                    "Allowed by you: " + ", ".join(cols)
                    if name in allowed and cols
                    else "Unavailable to QueryMind"
                ),
                "allowed": name in allowed and bool(cols),
                "columns": cols,
            }
        )
    host_label = (
        f"{workspace.db_name} on {workspace.host}"
        if workspace.host and workspace.db_name
        else "Discovered schema"
    )
    return {
        "source_name": host_label,
        "database": display_name(getattr(workspace, "engine", None)),
        "engine": getattr(workspace, "engine", "postgres"),
        "engine_choices": ENGINE_CHOICES,
        "business": workspace.business or "",
        "industry": workspace.industry or "",
        "keeps": workspace.keeps or [],
        "tables": tables,
        "updated_label": workspace.updated_at.strftime("%b %d, %Y"),
        "is_readonly_role": bool(workspace.is_readonly_role),
        "host": workspace.host,
        "db_name": workspace.db_name,
        "db_user": workspace.db_user,
        "allowed_tables": list(workspace.allowed_tables or []),
        "allowed_columns": dict(workspace.allowed_columns or {}),
    }


def product_context(request, extra=None):
    user = getattr(request, "user", None)
    workspace = workspace_for(user, KIND_CHAT) if user and user.is_authenticated else None
    profile = profile_from_workspace(workspace)
    recent = (
        Conversation.objects.for_user(user, kind=KIND_CHAT).order_by("-updated_at")[:20]
        if user and user.is_authenticated
        else Conversation.objects.none()
    )
    data_ready = chat_ready(workspace)
    api_workspace = (
        workspace_for(user, KIND_API) if user and user.is_authenticated else None
    )
    org = organization_for(user) if user and user.is_authenticated else None
    chat_on = org_chat_enabled(org) if org else False
    api_on = org_api_enabled(org) if org else False
    setup_step = next_setup_step(org) if org else None
    context = {
        "recent_conversations": recent,
        "data_ready": data_ready,
        "api_data_ready": api_db_ready(api_workspace),
        "signed_in": bool(user and user.is_authenticated),
        "account_name": (
            (user.get_full_name() or user.get_username())
            if user and user.is_authenticated
            else ""
        ),
        "profile": profile,
        "ai_display_name": AI_DISPLAY_NAME,
        "ai_avatar_text": AI_AVATAR_TEXT,
        "example_questions": EXAMPLE_QUESTIONS,
        "recent_limit": RECENT_CONVERSATIONS_LIMIT,
        "workspace": workspace,
        "is_org_admin": is_org_admin(user) if user and user.is_authenticated else False,
        "organization": org,
        "membership": active_membership(user) if user and user.is_authenticated else None,
        "engine_choices": ENGINE_CHOICES,
        "chat_enabled": chat_on,
        "api_enabled": api_on,
        "app_home_url_name": home_url_name(org) if org else "ask",
        "org_product_mode": org_product_mode(org) if org else "",
        "org_llm_backend": org_llm_backend(org) if org else "",
        "selectable_products": selectable_products(),
        "setup_step": setup_step,
        "show_setup_nav": bool(
            user
            and user.is_authenticated
            and is_org_admin(user)
            and setup_step
        ),
    }
    if extra:
        context.update(extra)
    return context
