import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, get_object_or_404, render, reverse
from django.template.defaultfilters import linebreaksbr
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.views import View
from django.views.generic import ListView, DetailView, TemplateView
import markdown

from connections.models import WorkspaceConnection
from connections.services.catalog import intersect_allow_lists
from connections.services.engines import normalize_engine
from connections.services.schema_discovery import filter_schema_to_tables
from connections.services.workspace import (
    WorkspaceConnectionError,
    apply_workspace_allow_list,
    discover_live_schema,
)


def authenticate_with_email(request, email: str, password: str):
    """Django stores createsuperuser username separately from email."""
    email = (email or "").strip().lower()
    if not email or not password:
        return None
    user = authenticate(request, username=email, password=password)
    if user is not None:
        return user
    match = (
        User.objects.filter(email__iexact=email).first()
        or User.objects.filter(username__iexact=email).first()
    )
    if match is None:
        return None
    return authenticate(request, username=match.username, password=password)


def user_for_login_email(email: str):
    email = (email or "").strip().lower()
    if not email:
        return None
    return (
        User.objects.filter(username__iexact=email).first()
        or User.objects.filter(email__iexact=email).first()
    )
from .product import (
    apply_llm_backend,
    apply_product_mode,
    home_url_name,
    next_setup_step,
    org_api_enabled,
    org_chat_enabled,
    org_mcp_enabled,
)

from .api_keys import (
    set_api_access_status,
    set_org_api_access_status,
)
from .key_portal import (
    create_access_request,
    handle_key_portal_post,
    portal_context,
)
from .dashboard import dashboard_context, post_login_redirect_name
from .models import (
    ApiAccessRequest,
    Conversation,
    Message,
    OrganizationMembership,
)
from .organizations import (
    apply_mcp_connection,
    create_member,
    ensure_organization_for_user,
    is_org_admin,
    is_org_member_active,
    is_platform_admin,
    mcp_server_url_for,
    organization_for,
    set_member_active,
)
from .services import ConversationService
from .constants import ERROR_MESSAGES, AI_AVATAR_TEXT
from .ui import (
    KIND_API,
    KIND_CHAT,
    api_ready,
    chat_ready,
    product_context,
    profile_from_workspace,
    workspace_for,
)


def render_markdown(content):
    md = markdown.Markdown(
        extensions=[
            "fenced_code",
            "tables",
            "nl2br",
        ]
    )
    return mark_safe(md.convert(escape(content)))


class LandingView(TemplateView):
    template_name = "landing.html"


class LoginView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect(post_login_redirect_name(request.user))
        return render(request, "auth/login.html")

    def post(self, request):
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password") or ""
        user = authenticate_with_email(request, email, password)
        if user is None:
            existing = user_for_login_email(email)
            inactive_membership = (
                existing
                and OrganizationMembership.objects.filter(
                    user=existing, is_active=False
                ).exists()
            )
            if existing and (not existing.is_active or inactive_membership):
                messages.error(request, "This account has been deactivated.")
                return render(request, "auth/login.html", status=403)
            messages.error(request, "That email or password did not match.")
            return render(request, "auth/login.html", status=400)
        if is_platform_admin(user):
            login(request, user)
            return redirect(post_login_redirect_name(user))
        if not is_org_member_active(user):
            membership = OrganizationMembership.objects.filter(user=user).first()
            if membership and not membership.is_active:
                messages.error(request, "This account has been deactivated.")
                return render(request, "auth/login.html", status=403)
            ensure_organization_for_user(user)
        login(request, user)
        return redirect(post_login_redirect_name(user))


class RegisterView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect(post_login_redirect_name(request.user))
        return render(request, "auth/register.html")

    def post(self, request):
        name = (request.POST.get("name") or "").strip()
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password") or ""
        confirm = request.POST.get("password_confirm") or ""

        def fail():
            return render(request, "auth/register.html", status=400)

        if not name or not email or not password:
            messages.error(request, "Name, email, and password are required.")
            return fail()
        if password != confirm:
            messages.error(request, "Passwords do not match.")
            return fail()
        if User.objects.filter(username=email).exists():
            messages.error(request, "An account with that email already exists.")
            return fail()
        try:
            validate_password(password)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return fail()
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=name[:150],
        )
        ensure_organization_for_user(user, name=name, defer_product=True)
        login(request, user)
        return redirect(_onboarding_next_url(organization_for(user)))


class AuthenticatedWorkspaceMixin(LoginRequiredMixin):
    login_url = "login"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            membership = OrganizationMembership.objects.filter(user=request.user).first()
            if membership and not membership.is_active:
                messages.error(request, "This account has been deactivated.")
                return redirect("login")
            if membership is None and not is_platform_admin(request.user):
                ensure_organization_for_user(request.user)
        return super().dispatch(request, *args, **kwargs)


class AdminRequiredMixin(AuthenticatedWorkspaceMixin):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            membership = OrganizationMembership.objects.filter(user=request.user).first()
            if membership and not membership.is_active:
                messages.error(request, "This account has been deactivated.")
                return redirect("login")
            if membership is None and not is_platform_admin(request.user):
                ensure_organization_for_user(request.user)
            if not is_org_admin(request.user) and not is_platform_admin(request.user):
                messages.error(
                    request,
                    "Only an organization administrator can manage this setting.",
                )
                return redirect(home_url_name(organization_for(request.user)))
        return super().dispatch(request, *args, **kwargs)


class OrgChatRequiredMixin:
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if is_platform_admin(request.user) and settings.CHAT_ENABLED:
                return super().dispatch(request, *args, **kwargs)
            org = organization_for(request.user)
            if not org_chat_enabled(org):
                messages.error(request, "This organization does not use chat.")
                return redirect(home_url_name(org))
        return super().dispatch(request, *args, **kwargs)


class OrgApiRequiredMixin:
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if is_platform_admin(request.user) and settings.API_ENABLED:
                return super().dispatch(request, *args, **kwargs)
            org = organization_for(request.user)
            if not org_api_enabled(org):
                messages.error(request, "This organization does not use the API.")
                return redirect(home_url_name(org))
        return super().dispatch(request, *args, **kwargs)


class OrgMcpRequiredMixin:
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if is_platform_admin(request.user) and settings.API_ENABLED:
                return super().dispatch(request, *args, **kwargs)
            org = organization_for(request.user)
            if not org_mcp_enabled(org):
                messages.error(request, "This organization does not use MCP.")
                return redirect(home_url_name(org))
        return super().dispatch(request, *args, **kwargs)


def _apply_portal_result(request, result):
    if result is None:
        return None
    if isinstance(result, JsonResponse):
        return result
    level = result.get("level") or "info"
    text = result.get("message") or ""
    if text:
        getattr(messages, level, messages.info)(request, text)
    return None


def _onboarding_next_url(org):
    step = next_setup_step(org)
    if step == "api":
        return reverse("onboarding") + "?track=api"
    if step == "chat":
        return reverse("onboarding") + "?track=chat"
    if step == "mcp":
        return reverse("onboarding") + "?track=mcp"
    if step == "product":
        return reverse("onboarding") + "?change=products"
    if org_chat_enabled(org):
        return reverse("ask")
    if org_api_enabled(org):
        return reverse("developers")
    if org_mcp_enabled(org):
        return reverse("mcp_docs")
    return reverse("dashboard")


def _wizard_plan(request, org):
    change_products = (request.GET.get("change") or request.POST.get("change") or "") == "products"
    track = (request.GET.get("track") or request.POST.get("track") or "").strip().lower()
    step = next_setup_step(org)
    if change_products or step == "product":
        return {
            "wizard_kind": KIND_CHAT,
            "show_product_step": True,
            "show_llm_step": False,
            "show_profile_steps": False,
            "show_db_steps": False,
            "show_mcp_steps": False,
            "track": "product",
            "finish_label": "Continue",
            "setup_action": "save_product",
        }
    if track not in {"chat", "api", "mcp"}:
        if step in {"chat", "api", "mcp"}:
            track = step
        elif org_mcp_enabled(org):
            track = "mcp"
        elif org_api_enabled(org) and not org_chat_enabled(org):
            track = "api"
        else:
            track = "chat"
    if track == "api":
        return {
            "wizard_kind": KIND_API,
            "show_product_step": False,
            "show_llm_step": True,
            "show_profile_steps": False,
            "show_db_steps": True,
            "show_mcp_steps": False,
            "track": "api",
            "finish_label": "Continue to API",
            "setup_action": "save_connection",
        }
    if track == "mcp":
        return {
            "wizard_kind": KIND_CHAT,
            "show_product_step": False,
            "show_llm_step": True,
            "show_profile_steps": False,
            "show_db_steps": False,
            "show_mcp_steps": True,
            "track": "mcp",
            "finish_label": "Continue to your MCP key",
            "setup_action": "save_mcp_setup",
        }
    return {
        "wizard_kind": KIND_CHAT,
        "show_product_step": False,
        "show_llm_step": True,
        "show_profile_steps": True,
        "show_db_steps": True,
        "show_mcp_steps": False,
        "track": "chat",
        "finish_label": "Ask your data",
        "setup_action": "save_connection",
    }


def _onboarding_context(request, plan, extra=None):
    kind = plan["wizard_kind"]
    context = product_context(request, {"active_nav": "onboarding", **plan})
    workspace = workspace_for(request.user, kind)
    context["profile"] = profile_from_workspace(workspace)
    if extra:
        context.update(extra)
    return context


def _parse_onboarding_connection(request):
    host = (request.POST.get("db_host") or "").strip()
    port = request.POST.get("db_port") or "5432"
    db_name = (request.POST.get("db_name") or "").strip()
    db_user = (request.POST.get("db_user") or "").strip()
    password = request.POST.get("db_password") or ""
    engine_raw = request.POST.get("engine") or request.POST.get("database") or "postgres"
    allowed = request.POST.getlist("allowed_tables")
    column_pairs = request.POST.getlist("allowed_columns")
    requested_columns: dict[str, list[str]] = {}
    for pair in column_pairs:
        if "." not in pair:
            continue
        table, column = pair.split(".", 1)
        requested_columns.setdefault(table, []).append(column)
    return host, port, db_name, db_user, password, engine_raw, allowed, requested_columns


def _save_live_workspace(request, *, kind: str):
    host, port, db_name, db_user, password, engine_raw, allowed, requested_columns = (
        _parse_onboarding_connection(request)
    )
    if not all([host, db_name, db_user, password]):
        return None, "Connect to a database first. QueryMind needs a live database connection."
    try:
        port_int = int(port)
        engine = normalize_engine(engine_raw)
        live = discover_live_schema(
            host=host,
            port=port_int,
            db_name=db_name,
            db_user=db_user,
            password=password,
            engine=engine,
        )
    except (TypeError, ValueError) as exc:
        return None, str(exc) if isinstance(exc, ValueError) else "Port must be a number."
    except WorkspaceConnectionError as exc:
        return None, exc.user_message
    allowed, allowed_columns = intersect_allow_lists(
        requested_tables=allowed,
        requested_columns=requested_columns,
        discovered_tables=live["tables"],
        discovered_columns=live["columns"],
    )
    if not allowed:
        return None, "Choose at least one table and column QueryMind may use. This is a security boundary."
    schema_text = filter_schema_to_tables(
        live["schema_text"],
        allowed,
        allowed_columns,
    )
    org = organization_for(request.user)
    workspace, _created = WorkspaceConnection.objects.update_or_create(
        user=request.user,
        kind=kind,
        defaults={
            "organization": org,
            "engine": engine,
            "host": host,
            "port": port_int,
            "db_name": db_name,
            "db_user": db_user,
            "schema_text": schema_text,
            "discovered_tables": live["tables"],
            "discovered_columns": live["columns"],
            "allowed_tables": allowed,
            "allowed_columns": allowed_columns,
            "industry": request.POST.get("industry") or "",
            "business": request.POST.get("business") or "",
            "keeps": request.POST.getlist("keeps"),
            "is_readonly_role": live["is_readonly_role"],
            "semantic_layer": live.get("semantic_layer") or {},
        },
    )
    workspace.set_password(password)
    workspace.save(update_fields=["password_ciphertext"])
    return workspace, None


class OnboardingDiscoverView(AdminRequiredMixin, View):
    def post(self, request):
        host = (request.POST.get("db_host") or "").strip()
        port = request.POST.get("db_port") or "5432"
        db_name = (request.POST.get("db_name") or "").strip()
        db_user = (request.POST.get("db_user") or "").strip()
        password = request.POST.get("db_password") or ""
        engine_raw = request.POST.get("engine") or request.POST.get("database") or "postgres"
        if not all([host, db_name, db_user, password]):
            return JsonResponse(
                {
                    "ok": False,
                    "error": "Host, database name, username, and password are required.",
                },
                status=400,
            )
        try:
            port_int = int(port)
            engine = normalize_engine(engine_raw)
        except (TypeError, ValueError) as exc:
            return JsonResponse(
                {"ok": False, "error": str(exc) if isinstance(exc, ValueError) else "Port must be a number."},
                status=400,
            )
        try:
            result = discover_live_schema(
                host=host,
                port=port_int,
                db_name=db_name,
                db_user=db_user,
                password=password,
                engine=engine,
            )
        except WorkspaceConnectionError as exc:
            return JsonResponse(
                {"ok": False, "error": exc.user_message, "detail": exc.detail},
                status=400,
            )
        return JsonResponse(
            {
                "ok": True,
                "tables": result["tables"],
                "columns": result["columns"],
                "is_readonly_role": result["is_readonly_role"],
                "engine": result["engine"],
            }
        )


class OnboardingView(AdminRequiredMixin, View):
    def get(self, request):
        org = organization_for(request.user)
        plan = _wizard_plan(request, org)
        return render(
            request,
            "onboarding/wizard.html",
            _onboarding_context(request, plan),
        )

    def post(self, request):
        org = organization_for(request.user)
        action = request.POST.get("action") or "save_connection"
        if action == "save_product":
            mode = apply_product_mode(org, request.POST.get("product"))
            if request.POST.get("llm_backend"):
                apply_llm_backend(org, request.POST.get("llm_backend"))
            if mode in {"api", "mcp"}:
                kind = (
                    ApiAccessRequest.KIND_MCP
                    if mode == "mcp"
                    else ApiAccessRequest.KIND_API
                )
                create_access_request(
                    request.user, kind, request.POST.get("key_note") or ""
                )
            org.refresh_from_db()
            return redirect(_onboarding_next_url(org))
        if action == "save_mcp_setup":
            if request.POST.get("llm_backend"):
                apply_llm_backend(org, request.POST.get("llm_backend"))
            raw = (request.POST.get("mcp_server_url") or "").strip()
            if raw and not raw.startswith(("http://", "https://")):
                messages.error(
                    request, "MCP server URL must start with http:// or https://."
                )
                plan = _wizard_plan(request, org)
                return render(
                    request,
                    "onboarding/wizard.html",
                    _onboarding_context(request, plan),
                    status=400,
                )
            org.mcp_server_url = raw
            token = (request.POST.get("mcp_access_token") or "").strip()
            apply_mcp_connection(
                org,
                url=raw,
                token=token or None,
                clear_token=bool(request.POST.get("clear_mcp_access_token")),
            )
            org.refresh_from_db()
            return redirect(_onboarding_next_url(org))
        plan = _wizard_plan(request, org)
        kind = KIND_API if plan["track"] == "api" else KIND_CHAT
        if request.POST.get("llm_backend"):
            apply_llm_backend(org, request.POST.get("llm_backend"))
            org.refresh_from_db()
        workspace, error = _save_live_workspace(request, kind=kind)
        if error:
            messages.error(request, error)
            return render(
                request,
                "onboarding/wizard.html",
                _onboarding_context(request, plan),
                status=400,
            )
        org.refresh_from_db()
        if kind == KIND_CHAT:
            return redirect(_onboarding_next_url(org))
        return redirect("developers")


class DataAccessView(AuthenticatedWorkspaceMixin, OrgChatRequiredMixin, View):
    def get(self, request):
        return render(
            request,
            "data_access.html",
            product_context(request, {"active_nav": "data"}),
        )

    def post(self, request):
        if not is_org_admin(request.user) and not is_platform_admin(request.user):
            messages.error(request, "Only an organization administrator can change table access.")
            return redirect("data_access")
        workspace = workspace_for(request.user, KIND_CHAT)
        if not chat_ready(workspace):
            messages.error(request, "Connect a database first, then choose tables and columns.")
            return redirect("onboarding")
        allowed = request.POST.getlist("allowed_tables")
        requested_columns: dict[str, list[str]] = {}
        for pair in request.POST.getlist("allowed_columns"):
            if "." not in pair:
                continue
            table, column = pair.split(".", 1)
            requested_columns.setdefault(table, []).append(column)
        try:
            apply_workspace_allow_list(
                workspace,
                requested_tables=allowed,
                requested_columns=requested_columns,
            )
        except WorkspaceConnectionError as exc:
            messages.error(request, exc.user_message)
            return render(
                request,
                "data_access.html",
                product_context(request, {"active_nav": "data"}),
                status=400,
            )
        messages.success(request, "Table and column access updated.")
        return redirect("data_access")


class DevelopersView(AuthenticatedWorkspaceMixin, OrgApiRequiredMixin, View):
    def get(self, request):
        workspace = workspace_for(request.user, KIND_API)
        origin = request.build_absolute_uri("/").rstrip("/")
        context = portal_context(request, ApiAccessRequest.KIND_API)
        return render(
            request,
            "developers.html",
            product_context(
                request,
                {
                    "active_nav": "api",
                    "api_ready": api_ready(workspace),
                    "api_origin": origin,
                    "docs_kind": "api",
                    **context,
                },
            ),
        )

    def post(self, request):
        result = handle_key_portal_post(request, ApiAccessRequest.KIND_API)
        response = _apply_portal_result(request, result)
        if response is not None:
            return response
        return redirect("developers")


class McpDocsView(AuthenticatedWorkspaceMixin, OrgMcpRequiredMixin, View):
    def get(self, request):
        origin = request.build_absolute_uri("/").rstrip("/")
        context = portal_context(request, ApiAccessRequest.KIND_MCP)
        return render(
            request,
            "mcp.html",
            product_context(
                request,
                {
                    "active_nav": "mcp",
                    "docs_kind": "mcp",
                    "api_origin": origin,
                    "mcp_server_url": mcp_server_url_for(request.user),
                    "mcp_token_configured": bool(
                        getattr(organization_for(request.user), "mcp_auth_ciphertext", "")
                    ),
                    **context,
                },
            ),
        )

    def post(self, request):
        result = handle_key_portal_post(request, ApiAccessRequest.KIND_MCP)
        response = _apply_portal_result(request, result)
        if response is not None:
            return response
        return redirect("mcp_docs")


class TeamView(AdminRequiredMixin, View):
    def get(self, request):
        org = organization_for(request.user)
        if org is None:
            messages.error(
                request,
                "Team and MCP URL are organization settings. Sign in as an organization admin.",
            )
            return redirect("dashboard")
        members = (
            OrganizationMembership.objects.filter(organization=org)
            .select_related("user")
            .order_by("role", "user__email")
        )
        activity = Conversation.objects.filter(organization=org).order_by("-updated_at")[:30]
        return render(
            request,
            "team.html",
            product_context(
                request,
                {
                    "active_nav": "team",
                    "members": members,
                    "org_activity": activity,
                    "new_member_password": request.session.pop("new_member_password", None),
                    "new_member_email": request.session.pop("new_member_email", None),
                    "mcp_token_configured": bool(org.mcp_auth_ciphertext),
                },
            ),
        )

    def post(self, request):
        action = request.POST.get("action")
        org = organization_for(request.user)
        if org is None:
            messages.error(
                request,
                "Team and MCP URL are organization settings. Sign in as an organization admin.",
            )
            return redirect("dashboard")
        if action == "save_product":
            apply_product_mode(org, request.POST.get("product"))
            if request.POST.get("llm_backend"):
                apply_llm_backend(org, request.POST.get("llm_backend"))
            org.refresh_from_db()
            messages.success(request, "Product settings saved.")
            step = next_setup_step(org)
            if step:
                return redirect(_onboarding_next_url(org))
            return redirect("team")
        if action == "save_llm":
            apply_llm_backend(org, request.POST.get("llm_backend"))
            messages.success(request, "Model saved.")
            return redirect("team")
        if action == "save_mcp":
            raw = (request.POST.get("mcp_server_url") or "").strip()
            if org is None:
                messages.error(
                    request,
                    "MCP URL belongs to an organization. Sign in as that organization's admin, then save the ServeEasy /mcp URL.",
                )
                return redirect("dashboard")
            if raw and not raw.startswith(("http://", "https://")):
                messages.error(request, "MCP server URL must start with http:// or https://.")
                return redirect("team")
            org.mcp_server_url = raw
            token = (request.POST.get("mcp_access_token") or "").strip()
            apply_mcp_connection(
                org,
                url=raw,
                token=token or None,
                clear_token=bool(request.POST.get("clear_mcp_access_token")),
            )
            messages.success(
                request,
                "MCP server saved." if raw else "MCP server cleared. Reads can use SQL; writes require MCP.",
            )
            return redirect("team")
        if action == "create":
            name = (request.POST.get("name") or "").strip()
            email = (request.POST.get("email") or "").strip().lower()
            password = request.POST.get("password") or secrets.token_urlsafe(9)
            if not name or not email:
                messages.error(request, "Name and email are required.")
                return redirect("team")
            try:
                validate_password(password)
                create_member(admin=request.user, email=email, name=name, password=password)
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
                return redirect("team")
            except (PermissionError, ValueError) as exc:
                messages.error(request, str(exc))
                return redirect("team")
            request.session["new_member_password"] = password
            request.session["new_member_email"] = email
            messages.success(
                request,
                "User created. Share the password now; QueryMind will not show it again.",
            )
            return redirect("team")
        if action in {"deactivate", "activate"}:
            user_id = request.POST.get("user_id")
            target = get_object_or_404(User, pk=user_id)
            try:
                set_member_active(
                    admin=request.user,
                    user=target,
                    is_active=action == "activate",
                )
            except PermissionError as exc:
                messages.error(request, str(exc))
                return redirect("team")
            messages.success(request, "User status updated.")
            return redirect("team")
        if action == "approve_api":
            request_id = request.POST.get("request_id")
            try:
                set_org_api_access_status(
                    org=org,
                    request_id=request_id,
                    status=ApiAccessRequest.STATUS_APPROVED,
                )
            except ApiAccessRequest.DoesNotExist:
                messages.error(request, "That API access request was not found.")
                return redirect("team")
            messages.success(request, "API access approved.")
            return redirect("team")
        return redirect("team")


class DashboardView(AdminRequiredMixin, View):
    def get(self, request):
        return render(request, "dashboard.html", dashboard_context(request))

    def post(self, request):
        org = organization_for(request.user)
        action = request.POST.get("action")
        if action == "save_product":
            apply_product_mode(org, request.POST.get("product"))
            if request.POST.get("llm_backend"):
                apply_llm_backend(org, request.POST.get("llm_backend"))
            org.refresh_from_db()
            messages.success(request, "Product settings saved.")
            step = next_setup_step(org)
            if step:
                return redirect(_onboarding_next_url(org))
            return redirect("dashboard")
        if action == "save_llm":
            apply_llm_backend(org, request.POST.get("llm_backend"))
            messages.success(request, "Model saved.")
            return redirect("dashboard")
        request_id = request.POST.get("request_id")
        if action == "approve_api":
            status = ApiAccessRequest.STATUS_APPROVED
            done = "API access approved."
        elif action == "deny_api":
            status = ApiAccessRequest.STATUS_DENIED
            done = "API access denied."
        else:
            return redirect("dashboard")
        try:
            set_api_access_status(
                actor=request.user,
                org=org,
                request_id=request_id,
                status=status,
            )
        except ApiAccessRequest.DoesNotExist:
            messages.error(request, "That API access request was not found.")
            return redirect("dashboard")
        messages.success(request, done)
        return redirect("dashboard")


class AskView(AuthenticatedWorkspaceMixin, OrgChatRequiredMixin, ListView):
    model = Conversation
    template_name = "homepage.html"
    context_object_name = "recent_conversations"

    def get_queryset(self):
        return Conversation.objects.for_user(self.request.user, kind=KIND_CHAT).order_by(
            "-updated_at"
        )[:20]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(product_context(self.request, {"active_nav": "ask"}))
        return context

    def post(self, request, *args, **kwargs):
        workspace = workspace_for(request.user, KIND_CHAT)
        if not chat_ready(workspace) and not mcp_server_url_for(request.user):
            if is_org_admin(request.user):
                messages.error(
                    request,
                    "Set up your database connection and allowed tables before asking.",
                )
                return redirect("onboarding")
            messages.error(
                request,
                "Your administrator has not connected a database yet.",
            )
            return redirect("ask")

        message_content = request.POST.get("message", "").strip()
        if not message_content:
            return HttpResponse("Message cannot be empty", status=400)

        conversation = Conversation.objects.create(
            user=request.user,
            workspace=workspace,
            organization=organization_for(request.user),
            title=(
                message_content[:50] + "..."
                if len(message_content) > 50
                else message_content
            ),
        )
        Message.objects.create(
            conversation=conversation, content=message_content, is_user=True
        )
        return redirect("chat", conversation_id=conversation.id)


HomepageView = AskView


class ChatView(AuthenticatedWorkspaceMixin, OrgChatRequiredMixin, DetailView):
    model = Conversation
    template_name = "chat.html"
    context_object_name = "conversation"
    pk_url_kwarg = "conversation_id"

    def get_queryset(self):
        return Conversation.objects.for_user(self.request.user, kind=KIND_CHAT)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        conversation = self.object

        messages_with_content = []
        for message in conversation.messages.all():
            if message.is_user:
                formatted_content = linebreaksbr(escape(message.content))
            else:
                formatted_content = render_markdown(message.content)

            messages_with_content.append(
                {"original": message, "formatted_content": formatted_content}
            )

        messages = list(conversation.messages.all())
        pending_stream = messages[-1] if messages and messages[-1].is_user else None

        context.update(
            product_context(
                self.request,
                {
                    "messages": conversation.messages.all(),
                    "messages_with_content": messages_with_content,
                    "pending_stream": pending_stream,
                    "active_nav": "ask",
                },
            )
        )
        return context

    def post(self, request, conversation_id):
        workspace = workspace_for(request.user, KIND_CHAT)
        if not chat_ready(workspace) and not mcp_server_url_for(request.user):
            return HttpResponse(
                "Set up your data before asking. QueryMind will not invent answers.",
                status=403,
            )

        message_content = request.POST.get("message", "").strip()
        if not message_content:
            return HttpResponse(ERROR_MESSAGES["EMPTY_MESSAGE"], status=400)

        conversation = get_object_or_404(
            Conversation.objects.for_user(request.user, kind=KIND_CHAT),
            id=conversation_id,
        )
        user_message = ConversationService.add_user_message(
            conversation, message_content
        )
        user_formatted = linebreaksbr(escape(user_message.content))
        timestamp = (
            user_message.timestamp.astimezone()
            .strftime("%I:%M %p")
            .lstrip("0")
            .replace(" 0", " ")
        )
        mid = user_message.id
        cid = conversation.id

        return HttpResponse(
            f"""
    <div class="message-row user fade-in">
        <div class="message-bubble user-message">
            <div>{user_formatted}</div>
            <span class="msg-time">{timestamp}</span>
        </div>
    </div>
    <div class="message-row fade-in"
         data-stream-url="/chat/{cid}/stream/?message_id={mid}"
         data-message-id="{mid}"
         data-conversation-id="{cid}">
        <div class="ai-avatar">{AI_AVATAR_TEXT}</div>
        <div class="message-bubble ai-message">
            <ul class="status-timeline" id="query-status-{mid}"></ul>
            <div class="markdown-content" id="ai-content-{mid}"></div>
            <div id="query-results-{mid}" class="query-results"></div>
            <div class="error-card" id="error-card-{mid}" hidden></div>
            <details class="how-answered" id="sql-panel-{mid}" hidden>
                <summary>How this was answered</summary>
                <p class="page-meta" id="answer-meta-{mid}"></p>
                <pre><code id="sql-code-{mid}"></code></pre>
            </details>
            <span class="msg-time" id="ai-timestamp-{mid}"></span>
        </div>
    </div>
"""
        )
