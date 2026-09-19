"""Organization administrator overview and action catalog."""

from __future__ import annotations

from types import SimpleNamespace
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from connections.services.engines import display_name

from chat.models import (
    ApiAccessRequest,
    ApiKey,
    Conversation,
    Organization,
    OrganizationMembership,
)
from chat.organizations import is_org_admin, is_platform_admin, organization_for
from chat.ui import (
    KIND_API,
    KIND_CHAT,
    api_db_ready,
    api_ready,
    chat_ready,
    product_context,
    workspace_for,
)
from chat.product import org_api_enabled, org_chat_enabled, org_mcp_enabled


def post_login_redirect_name(user) -> str:
    from chat.product import home_url_name, next_setup_step

    if is_platform_admin(user):
        return "dashboard"
    org = organization_for(user)
    if is_org_admin(user) and next_setup_step(org):
        return "onboarding"
    if is_org_admin(user):
        return "dashboard"
    return home_url_name(org)


def dashboard_context(request):
    if is_platform_admin(request.user):
        return _platform_dashboard_context(request)
    return _org_dashboard_context(request)


def _platform_dashboard_context(request):
    pending_api = (
        ApiAccessRequest.objects.filter(status=ApiAccessRequest.STATUS_PENDING)
        .select_related("user")
        .prefetch_related("user__org_memberships__organization")
        .order_by("created_at")
    )
    pending_count = pending_api.count()
    org_count = Organization.objects.count()
    people_count = OrganizationMembership.objects.filter(is_active=True).count()
    approved_api = ApiAccessRequest.objects.filter(
        status=ApiAccessRequest.STATUS_APPROVED
    ).count()
    active_keys = ApiKey.objects.filter(revoked_at__isnull=True).count()
    recent_questions = Conversation.objects.select_related("user").order_by("-updated_at")[:8]
    stats = [
        {
            "label": "Organizations",
            "value": str(org_count),
            "hint": "Every QueryMind customer organization.",
            "tone": "ok",
        },
        {
            "label": "People",
            "value": str(people_count),
            "hint": "Active memberships across organizations.",
        },
        {
            "label": "API access",
            "value": str(pending_count),
            "hint": f"{pending_count} waiting · {approved_api} approved · {active_keys} active keys",
            "tone": "warn" if pending_count else "ok",
        },
        {
            "label": "Questions",
            "value": str(Conversation.objects.count()),
            "hint": "Titles only. Message content stays with the person who asked.",
        },
    ]
    actions = [
        {
            "title": "Approve API access",
            "body": "People request keys from the API page. Approve them here before they can call QueryMind.",
            "href": "dashboard",
            "anchor": "api-requests",
            "cta": "Review requests",
            "icon": "bi-key",
            "status": f"{pending_count} waiting" if pending_count else "None waiting",
            "tone": "warn" if pending_count else "ok",
        },
        {
            "title": "Staff admin",
            "body": "Organizations, memberships, MCP URLs, and API keys.",
            "href": "admin:index",
            "cta": "Open staff admin",
            "icon": "bi-shield-lock",
            "status": "Super administrator",
            "tone": "ok",
        },
        {
            "title": "Create an API key",
            "body": "Do not mint a superuser key for ServeEasy. Sign in as an organization admin, set mcp_server_url to ServeEasy /mcp, then mint that user's key.",
            "href": "developers",
            "cta": "Open API",
            "icon": "bi-code-slash",
            "status": "Org key required",
            "tone": "warn",
        },
    ]
    alerts = []
    if pending_count:
        alerts.append(
            {
                "title": f"{pending_count} API access request{'s' if pending_count != 1 else ''} waiting",
                "body": "Approve a request before that person can create API keys.",
                "href": "dashboard",
                "label": "Review below",
                "anchor": "api-requests",
            }
        )
    return product_context(
        request,
        {
            "active_nav": "dashboard",
            "dash_org": SimpleNamespace(name="QueryMind"),
            "dash_platform": True,
            "dash_stats": stats,
            "dash_actions": actions,
            "dash_alerts": alerts,
            "dash_questions": recent_questions,
            "dash_pending_api": pending_api,
            "dash_allowed_tables": [],
            "dash_allowed_more": 0,
            "dash_readonly": False,
            "dash_api_workspace": None,
        },
    )


def _org_dashboard_context(request):
    org = organization_for(request.user)
    members = OrganizationMembership.objects.filter(organization=org).select_related(
        "user"
    )
    member_ids = list(members.values_list("user_id", flat=True))
    active_people = members.filter(is_active=True).count()
    deactivated_people = members.filter(is_active=False).count()
    created_users = members.filter(role=OrganizationMembership.ROLE_MEMBER).count()

    chat_workspace = workspace_for(request.user, KIND_CHAT)
    api_workspace = workspace_for(request.user, KIND_API)
    data_is_ready = chat_ready(chat_workspace)
    allowed_tables = list((chat_workspace.allowed_tables or []) if chat_workspace else [])
    discovered_tables = list(
        (chat_workspace.discovered_tables or []) if chat_workspace else []
    )

    week_ago = timezone.now() - timedelta(days=7)
    questions = Conversation.objects.filter(
        Q(organization=org) | Q(user_id__in=member_ids)
    ).distinct()
    question_count = questions.count()
    recent_questions = questions.select_related("user").order_by("-updated_at")[:8]
    week_questions = questions.filter(updated_at__gte=week_ago).count()

    pending_api = (
        ApiAccessRequest.objects.filter(
            user_id__in=member_ids,
            status=ApiAccessRequest.STATUS_PENDING,
        )
        .select_related("user")
        .order_by("created_at")
    )
    pending_count = pending_api.count()
    approved_api = ApiAccessRequest.objects.filter(
        user_id__in=member_ids,
        status=ApiAccessRequest.STATUS_APPROVED,
    ).count()
    active_keys = ApiKey.objects.filter(
        user_id__in=member_ids,
        revoked_at__isnull=True,
    ).count()

    mcp_url = (org.mcp_server_url or "").strip() if org else ""
    chat_on = org_chat_enabled(org)
    api_on = org_api_enabled(org)
    mcp_on = org_mcp_enabled(org)
    api_is_ready = api_db_ready(api_workspace) or api_ready(api_workspace)

    stats = [
        {
            "label": "People",
            "value": str(active_people),
            "hint": (
                f"{created_users} user{'s' if created_users != 1 else ''} you created"
                + (f" · {deactivated_people} deactivated" if deactivated_people else "")
            ),
        },
        {
            "label": "Chat data",
            "value": "Ready" if data_is_ready else "Not connected",
            "hint": (
                f"{len(allowed_tables)} of {len(discovered_tables)} tables allowed · {display_name(chat_workspace.engine)}"
                if data_is_ready and chat_workspace
                else "Connect a database, then choose tables."
            ),
            "tone": "ok" if data_is_ready else "warn",
        },
        {
            "label": "Questions",
            "value": str(question_count),
            "hint": f"{week_questions} in the last 7 days. Titles only — messages stay private.",
        },
        {
            "label": "MCP server",
            "value": "Configured" if mcp_url else "Not set",
            "hint": mcp_url or "Writes and business actions need an MCP server.",
            "tone": "ok" if mcp_url else "muted",
        },
    ]
    if api_on or mcp_on:
        stats.append(
            {
                "label": "Key access",
                "value": str(pending_count),
                "hint": (
                    f"{pending_count} waiting · {approved_api} approved · {active_keys} active keys"
                ),
                "tone": "warn" if pending_count else "ok",
            }
        )

    actions = _admin_actions(
        chat_on=chat_on,
        api_on=api_on,
        mcp_on=mcp_on,
        data_ready=data_is_ready,
        api_ready=api_is_ready,
        mcp_set=bool(mcp_url),
        pending_api=pending_count,
    )

    alerts = []
    if chat_on and not data_is_ready:
        alerts.append(
            {
                "title": "Chat is not ready yet",
                "body": "Finish connecting the organization’s database and confirm which tables QueryMind may use.",
                "href": "onboarding",
                "query": "track=chat",
                "label": "Set up your data",
            }
        )
    if api_on and not api_is_ready:
        alerts.append(
            {
                "title": "API has no database yet",
                "body": "Connect a separate API database so QueryMind can rediscover tables after restart.",
                "href": "onboarding",
                "query": "track=api",
                "label": "Set up API data",
            }
        )
    if (api_on or mcp_on) and pending_count:
        alerts.append(
            {
                "title": f"{pending_count} key request{'s' if pending_count != 1 else ''} waiting",
                "body": "Approve a request before that person can copy a key.",
                "href": "dashboard",
                "label": "Review below",
                "anchor": "api-requests",
            }
        )

    return product_context(
        request,
        {
            "active_nav": "dashboard",
            "dash_org": org,
            "dash_stats": stats,
            "dash_actions": actions,
            "dash_alerts": alerts,
            "dash_questions": recent_questions,
            "dash_pending_api": pending_api,
            "dash_allowed_tables": allowed_tables[:8],
            "dash_allowed_more": max(0, len(allowed_tables) - 8),
            "dash_readonly": bool(chat_workspace and chat_workspace.is_readonly_role),
            "dash_api_workspace": api_workspace,
        },
    )


def _admin_actions(*, chat_on, api_on, mcp_on, data_ready, api_ready, mcp_set, pending_api):
    actions = []
    if settings.CHAT_ENABLED and settings.API_ENABLED:
        actions.append(
            {
                "title": "Change products",
                "body": "Switch between chat, API, or MCP. Existing connections stay saved.",
                "href": "onboarding",
                "query": "change=products",
                "cta": "Change products",
                "icon": "bi-toggles",
                "status": "Administrator only",
                "tone": "ok",
            }
        )
    if chat_on:
        actions.append(
            {
                "title": "Connect or change the database",
                "body": "QueryMind reads live table names from your database. You choose what it may use.",
                "href": "onboarding",
                "query": "track=chat",
                "cta": "Set up data" if not data_ready else "Change connection",
                "icon": "bi-sliders",
                "status": "Needs setup" if not data_ready else "Connected",
                "tone": "warn" if not data_ready else "ok",
            }
        )
        actions.append(
            {
                "title": "Review allowed tables",
                "body": "Give or remove table and column permission on this page. You do not need to restart setup.",
                "href": "data_access",
                "cta": "Edit table access" if data_ready else "Open your data",
                "icon": "bi-database",
                "status": "Ready" if data_ready else "Empty",
                "tone": "ok" if data_ready else "muted",
            }
        )
        actions.append(
            {
                "title": "Ask a question",
                "body": "Start a chat in plain English. Answers come only from tables you allowed.",
                "href": "ask",
                "cta": "New question",
                "icon": "bi-chat-dots",
                "status": "Available" if data_ready else "Needs data",
                "tone": "ok" if data_ready else "muted",
            }
        )
    actions.append(
        {
            "title": "Create and manage users",
            "body": "Add people to this organization, then activate or deactivate their login.",
            "href": "team",
            "cta": "Open team",
            "icon": "bi-people",
            "status": "Administrator only",
            "tone": "ok",
        }
    )
    actions.append(
        {
            "title": "Configure the MCP server",
            "body": "Writes and business actions only run through MCP. Reads can still use SQL.",
            "href": "team",
            "cta": "Set MCP URL",
            "icon": "bi-hdd-network",
            "status": "Configured" if mcp_set else "Not set",
            "tone": "ok" if mcp_set else "muted",
        }
    )
    if mcp_on:
        actions.append(
            {
                "title": "Open the MCP portal",
                "body": "Request or copy an MCP key after staff approval.",
                "href": "mcp_docs",
                "cta": "Open MCP",
                "icon": "bi-plug",
                "status": "Configured" if mcp_set else "URL not set",
                "tone": "ok" if mcp_set else "muted",
            }
        )
        actions.append(
            {
                "title": "Approve MCP keys",
                "body": "After approval the requester can copy the key with their password.",
                "href": "dashboard",
                "anchor": "api-requests",
                "cta": "Review requests",
                "icon": "bi-key",
                "status": f"{pending_api} waiting" if pending_api else "None waiting",
                "tone": "warn" if pending_api else "ok",
            }
        )
    if api_on:
        actions.append(
            {
                "title": "Connect the API database",
                "body": "Store API credentials separately from chat so QueryMind can reconnect after restart.",
                "href": "onboarding",
                "query": "track=api",
                "cta": "Set up API data" if not api_ready else "Change API data",
                "icon": "bi-hdd-network",
                "status": "Needs setup" if not api_ready else "Connected",
                "tone": "warn" if not api_ready else "ok",
            }
        )
        actions.append(
            {
                "title": "Approve API access",
                "body": "People request keys here. Approve a request before they can call the API.",
                "href": "dashboard",
                "anchor": "api-requests",
                "cta": "Review requests",
                "icon": "bi-key",
                "status": f"{pending_api} waiting" if pending_api else "None waiting",
                "tone": "warn" if pending_api else "ok",
            }
        )
        actions.append(
            {
                "title": "Open the API portal",
                "body": "Docs, access requests, and keys. API database credentials are stored separately from chat.",
                "href": "developers",
                "cta": "Open API",
                "icon": "bi-code-slash",
                "status": "Catalog ready" if api_ready else "No API catalog yet",
                "tone": "ok" if api_ready else "muted",
            }
        )
    return actions
