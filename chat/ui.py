"""Shared template context for QueryMind product UI."""

from connections.models import WorkspaceConnection

from .constants import (
    AI_AVATAR_TEXT,
    AI_DISPLAY_NAME,
    EXAMPLE_QUESTIONS,
    RECENT_CONVERSATIONS_LIMIT,
)
from .models import Conversation

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


def workspace_for(user):
    if not user or not user.is_authenticated:
        return None
    return WorkspaceConnection.objects.filter(user=user).first()


def profile_from_workspace(workspace):
    if not workspace:
        return DEFAULT_PROFILE
    allowed = {str(name) for name in (workspace.allowed_tables or [])}
    tables = []
    for name in workspace.discovered_tables or []:
        tables.append(
            {
                "name": name,
                "description": (
                    "Allowed by you"
                    if name in allowed
                    else "Unavailable to QueryMind"
                ),
                "allowed": name in allowed,
            }
        )
    host_label = f"{workspace.db_name} on {workspace.host}"
    return {
        "source_name": host_label,
        "database": "PostgreSQL",
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
    }


def product_context(request, extra=None):
    user = getattr(request, "user", None)
    workspace = workspace_for(user) if user and user.is_authenticated else None
    profile = profile_from_workspace(workspace)
    recent = (
        Conversation.objects.for_user(user).order_by("-updated_at")[:20]
        if user and user.is_authenticated
        else Conversation.objects.none()
    )
    data_ready = bool(workspace and workspace.allowed_tables)
    context = {
        "recent_conversations": recent,
        "data_ready": data_ready,
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
    }
    if extra:
        context.update(extra)
    return context
