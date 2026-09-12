import markdown
from django.shortcuts import redirect, get_object_or_404, render
from django.http import HttpResponse
from django.views import View
from django.views.generic import ListView, DetailView, TemplateView
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.template.defaultfilters import linebreaksbr
from django.utils.html import escape
from django.utils.safestring import mark_safe
from .models import Conversation, Message
from .services import ConversationService
from .constants import ERROR_MESSAGES, AI_AVATAR_TEXT
from .ui import product_context


def render_markdown(content):
    """Convert markdown to HTML safely"""
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
        return render(request, "auth/login.html")

    def post(self, request):
        request.session["querymind_signed_in"] = True
        request.session["querymind_name"] = request.POST.get("email", "").split("@")[0]
        if request.session.get("querymind_onboarded"):
            return redirect("ask")
        return redirect("onboarding")


class RegisterView(View):
    def get(self, request):
        return render(request, "auth/register.html")

    def post(self, request):
        request.session["querymind_signed_in"] = True
        request.session["querymind_name"] = request.POST.get("name") or "Workspace"
        return redirect("onboarding")


class OnboardingView(View):
    def get(self, request):
        return render(
            request,
            "onboarding/wizard.html",
            product_context(request, {"active_nav": "onboarding"}),
        )

    def post(self, request):
        allowed = request.POST.getlist("allowed_tables")
        keeps = request.POST.getlist("keeps")
        paste = request.POST.get("schema_paste", "")
        discovered = []
        for line in paste.splitlines():
            token = line.strip().split()[0] if line.strip() else ""
            if token and token.isidentifier():
                discovered.append(token)
        if not discovered:
            discovered = allowed or ["customers", "orders", "products", "payments"]
        tables = []
        for name in discovered:
            tables.append(
                {
                    "name": name,
                    "description": "Included in your knowledge profile",
                    "allowed": name in allowed if allowed else True,
                }
            )
        if allowed and not tables:
            tables = [
                {"name": name, "description": "Allowed by you", "allowed": True}
                for name in allowed
            ]
        profile = {
            "source_name": request.POST.get("database") or "Connected database",
            "database": request.POST.get("database") or "PostgreSQL",
            "business": request.POST.get("business") or "",
            "industry": request.POST.get("industry") or "",
            "keeps": keeps,
            "tables": tables,
            "updated_label": "just now",
        }
        request.session["querymind_profile"] = profile
        request.session["querymind_onboarded"] = True
        request.session["querymind_signed_in"] = True
        return redirect("ask")


class DataAccessView(View):
    def get(self, request):
        return render(
            request,
            "data_access.html",
            product_context(request, {"active_nav": "data"}),
        )


class AskView(ListView):
    model = Conversation
    template_name = "homepage.html"
    context_object_name = "recent_conversations"
    queryset = Conversation.objects.all().order_by("-updated_at")[:20]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(product_context(self.request, {"active_nav": "ask"}))
        return context

    def post(self, request, *args, **kwargs):
        message_content = request.POST.get("message", "").strip()

        if not message_content:
            return HttpResponse("Message cannot be empty", status=400)

        conversation = Conversation.objects.create(
            title=(
                message_content[:50] + "..."
                if len(message_content) > 50
                else message_content
            )
        )

        Message.objects.create(
            conversation=conversation, content=message_content, is_user=True
        )

        return redirect("chat", conversation_id=conversation.id)


HomepageView = AskView


@method_decorator(csrf_exempt, name="dispatch")
class ChatView(DetailView):
    """Individual chat conversation view - handles both GET and POST"""

    model = Conversation
    template_name = "chat.html"
    context_object_name = "conversation"
    pk_url_kwarg = "conversation_id"

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
        """Handle new messages in existing chat - returns HTML with SSE endpoint info"""
        message_content = request.POST.get("message", "").strip()

        if not message_content:
            return HttpResponse(ERROR_MESSAGES["EMPTY_MESSAGE"], status=400)

        conversation = get_object_or_404(Conversation, id=conversation_id)

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
