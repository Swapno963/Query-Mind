import markdown
from django.shortcuts import redirect, get_object_or_404
from django.http import HttpResponse
from django.views.generic import ListView, DetailView
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.template.defaultfilters import linebreaksbr
from django.utils.html import escape
from django.utils.safestring import mark_safe

from .models import Conversation, Message
from .services import ConversationService
from .constants import (
    ERROR_MESSAGES,
)


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


@method_decorator(csrf_exempt, name="dispatch")
class HomepageView(ListView):
    """Claude.ai-style homepage showing recent conversations"""

    model = Conversation
    template_name = "homepage.html"
    context_object_name = "recent_conversations"
    queryset = Conversation.objects.all().order_by("-updated_at")[:20]

    def post(self, request, *args, **kwargs):
        """Handle new conversation creation from homepage"""
        message_content = request.POST.get("message", "").strip()

        if not message_content:
            return HttpResponse("Message cannot be empty", status=400)

        # Create new conversation
        conversation = Conversation.objects.create(
            title=(
                message_content[:50] + "..."
                if len(message_content) > 50
                else message_content
            )
        )

        # Save the initial message
        Message.objects.create(
            conversation=conversation, content=message_content, is_user=True
        )

        # Redirect to the new chat where streaming will occur
        return redirect("chat", conversation_id=conversation.id)


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

        # Process messages for display
        messages_with_content = []
        for message in conversation.messages.all():
            if message.is_user:
                # User messages: simple line breaks
                formatted_content = linebreaksbr(escape(message.content))
            else:
                # AI messages: render markdown
                formatted_content = render_markdown(message.content)

            messages_with_content.append(
                {"original": message, "formatted_content": formatted_content}
            )

        messages = list(conversation.messages.all())
        pending_stream = (
            messages[-1] if messages and messages[-1].is_user else None
        )

        context.update(
            {
                "messages": conversation.messages.all(),
                "messages_with_content": messages_with_content,
                "recent_conversations": Conversation.objects.order_by("-updated_at")[
                    :20
                ],
                "ai_display_name": AI_DISPLAY_NAME,
                "ai_avatar_text": AI_AVATAR_TEXT,
                "pending_stream": pending_stream,
            }
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
         data-conversation-id="{cid}"
         data-model-name="{AI_DISPLAY_NAME}">
        <div class="ai-avatar">{AI_AVATAR_TEXT}</div>
        <div class="message-bubble ai-message">
            <div class="stream-status visible" id="query-status-{mid}">Thinking…</div>
            <details class="sql-panel" id="sql-panel-{mid}" hidden>
                <summary>Generated SQL</summary>
                <pre><code id="sql-code-{mid}"></code></pre>
            </details>
            <div class="markdown-content" id="ai-content-{mid}"></div>
            <div id="query-results-{mid}" class="query-results"></div>
            <span class="msg-time" id="ai-timestamp-{mid}"></span>
        </div>
    </div>
"""
        )
