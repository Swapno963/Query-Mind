"""Shared template context for QueryMind product UI."""

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
}


def product_context(request, extra=None):
    profile = request.session.get("querymind_profile") or DEFAULT_PROFILE
    context = {
        "recent_conversations": Conversation.objects.order_by("-updated_at")[:20],
        "data_ready": bool(request.session.get("querymind_onboarded")),
        "signed_in": bool(request.session.get("querymind_signed_in")),
        "account_name": request.session.get("querymind_name") or "",
        "profile": profile,
        "ai_display_name": AI_DISPLAY_NAME,
        "ai_avatar_text": AI_AVATAR_TEXT,
        "example_questions": EXAMPLE_QUESTIONS,
        "recent_limit": RECENT_CONVERSATIONS_LIMIT,
    }
    if extra:
        context.update(extra)
    return context
