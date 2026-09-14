import json

from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, get_object_or_404, render
from django.template.defaultfilters import linebreaksbr
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.views import View
from django.views.generic import ListView, DetailView, TemplateView
import markdown

from connections.models import WorkspaceConnection
from connections.services.catalog import intersect_allow_lists
from connections.services.schema_discovery import filter_schema_to_tables
from connections.services.workspace import (
    WorkspaceConnectionError,
    discover_live_schema,
)

from .api_keys import generate_api_key, user_has_approved_api_access
from .models import ApiAccessRequest, ApiKey, Conversation, Message
from .services import ConversationService
from .constants import ERROR_MESSAGES, AI_AVATAR_TEXT
from .ui import (
    KIND_API,
    KIND_CHAT,
    api_ready,
    chat_ready,
    product_context,
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
            return redirect("ask")
        return render(request, "auth/login.html")

    def post(self, request):
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password") or ""
        user = authenticate(request, username=email, password=password)
        if user is None:
            messages.error(request, "That email or password did not match.")
            return render(request, "auth/login.html", status=400)
        login(request, user)
        return redirect("ask")


class RegisterView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect("ask")
        product = (request.GET.get("product") or "chat").strip().lower()
        if product not in {"chat", "api"}:
            product = "chat"
        return render(request, "auth/register.html", {"product": product})

    def post(self, request):
        name = (request.POST.get("name") or "").strip()
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password") or ""
        confirm = request.POST.get("password_confirm") or ""
        product = (request.POST.get("product") or "chat").strip().lower()
        if product not in {"chat", "api"}:
            product = "chat"

        def fail():
            return render(request, "auth/register.html", {"product": product}, status=400)

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
        login(request, user)
        if product == "api":
            return redirect("developers")
        return redirect("onboarding")


class AuthenticatedWorkspaceMixin(LoginRequiredMixin):
    login_url = "login"


class OnboardingDiscoverView(AuthenticatedWorkspaceMixin, View):
    def post(self, request):
        host = (request.POST.get("db_host") or "").strip()
        port = request.POST.get("db_port") or "5432"
        db_name = (request.POST.get("db_name") or "").strip()
        db_user = (request.POST.get("db_user") or "").strip()
        password = request.POST.get("db_password") or ""
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
        except (TypeError, ValueError):
            return JsonResponse(
                {"ok": False, "error": "Port must be a number."},
                status=400,
            )
        try:
            result = discover_live_schema(
                host=host,
                port=port_int,
                db_name=db_name,
                db_user=db_user,
                password=password,
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
            }
        )


class OnboardingView(AuthenticatedWorkspaceMixin, View):
    def get(self, request):
        return render(
            request,
            "onboarding/wizard.html",
            product_context(request, {"active_nav": "onboarding"}),
        )

    def post(self, request):
        host = (request.POST.get("db_host") or "").strip()
        port = request.POST.get("db_port") or "5432"
        db_name = (request.POST.get("db_name") or "").strip()
        db_user = (request.POST.get("db_user") or "").strip()
        password = request.POST.get("db_password") or ""
        allowed = request.POST.getlist("allowed_tables")
        column_pairs = request.POST.getlist("allowed_columns")
        requested_columns: dict[str, list[str]] = {}
        for pair in column_pairs:
            if "." not in pair:
                continue
            table, column = pair.split(".", 1)
            requested_columns.setdefault(table, []).append(column)
        if not all([host, db_name, db_user, password]):
            messages.error(
                request,
                "Connect to PostgreSQL first. QueryMind needs a live database connection.",
            )
            return render(
                request,
                "onboarding/wizard.html",
                product_context(request, {"active_nav": "onboarding"}),
                status=400,
            )
        try:
            port_int = int(port)
            live = discover_live_schema(
                host=host,
                port=port_int,
                db_name=db_name,
                db_user=db_user,
                password=password,
            )
        except WorkspaceConnectionError as exc:
            messages.error(request, exc.user_message)
            return render(
                request,
                "onboarding/wizard.html",
                product_context(request, {"active_nav": "onboarding"}),
                status=400,
            )
        live_names = set(live["tables"])
        allowed, allowed_columns = intersect_allow_lists(
            requested_tables=allowed,
            requested_columns=requested_columns,
            discovered_tables=live["tables"],
            discovered_columns=live["columns"],
        )
        if not allowed:
            messages.error(
                request,
                "Choose at least one table and column QueryMind may use. This is a security boundary.",
            )
            return render(
                request,
                "onboarding/wizard.html",
                product_context(request, {"active_nav": "onboarding"}),
                status=400,
            )
        schema_text = filter_schema_to_tables(
            live["schema_text"],
            allowed,
            allowed_columns,
        )
        workspace, _created = WorkspaceConnection.objects.update_or_create(
            user=request.user,
            kind=KIND_CHAT,
            defaults={
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
            },
        )
        workspace.set_password(password)
        workspace.save(update_fields=["password_ciphertext"])
        return redirect("ask")


class DataAccessView(AuthenticatedWorkspaceMixin, View):
    def get(self, request):
        return render(
            request,
            "data_access.html",
            product_context(request, {"active_nav": "data"}),
        )


class DevelopersView(AuthenticatedWorkspaceMixin, View):
    def get(self, request):
        latest = request.user.api_access_requests.order_by("-created_at").first()
        approved = user_has_approved_api_access(request.user)
        workspace = workspace_for(request.user, KIND_API)
        origin = request.build_absolute_uri("/").rstrip("/")
        new_key = request.session.pop("new_api_key", None)
        return render(
            request,
            "developers.html",
            product_context(
                request,
                {
                    "active_nav": "api",
                    "api_status": latest.status if latest else "none",
                    "api_approved": approved,
                    "api_ready": api_ready(workspace),
                    "api_key_prefixes": list(
                        request.user.api_keys.filter(revoked_at__isnull=True).values_list(
                            "prefix", flat=True
                        )
                    ),
                    "new_api_key": new_key,
                    "api_origin": origin,
                },
            ),
        )

    def post(self, request):
        action = request.POST.get("action")
        if action == "request":
            if user_has_approved_api_access(request.user):
                messages.success(request, "API access is already approved.")
            elif request.user.api_access_requests.filter(
                status=ApiAccessRequest.STATUS_PENDING
            ).exists():
                messages.info(request, "Your API access request is waiting for approval.")
            else:
                ApiAccessRequest.objects.create(
                    user=request.user,
                    note=(request.POST.get("note") or "").strip(),
                )
                messages.success(request, "Request sent. A QueryMind admin must approve it.")
        elif action == "create_key":
            if not user_has_approved_api_access(request.user):
                messages.error(
                    request,
                    "Your API access request has not been approved yet.",
                )
            else:
                raw, prefix, hashed = generate_api_key()
                ApiKey.objects.create(user=request.user, prefix=prefix, key_hash=hashed)
                request.session["new_api_key"] = raw
                messages.success(
                    request,
                    "Store this key now. QueryMind will not show it again.",
                )
        return redirect("developers")


class AskView(AuthenticatedWorkspaceMixin, ListView):
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
        if not chat_ready(workspace):
            messages.error(
                request,
                "Set up your PostgreSQL connection and allowed tables before asking.",
            )
            return redirect("onboarding")

        message_content = request.POST.get("message", "").strip()
        if not message_content:
            return HttpResponse("Message cannot be empty", status=400)

        conversation = Conversation.objects.create(
            user=request.user,
            workspace=workspace,
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


class ChatView(AuthenticatedWorkspaceMixin, DetailView):
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
        if not chat_ready(workspace):
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
