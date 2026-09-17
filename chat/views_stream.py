import json
import random
import time

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, StreamingHttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.generic import View
from django.views.generic.detail import SingleObjectMixin

from agent.graph import build_on_premise_graph
from agent.state import QueryMindState
from chat.ui import KIND_CHAT, chat_ready, workspace_for

from .constants import ERROR_MESSAGES
from .models import Conversation, Message
from .services import ConversationService
from .views import render_markdown


class StreamChatViewGraph(LoginRequiredMixin, SingleObjectMixin, View):
    login_url = "login"
    model = Conversation
    pk_url_kwarg = "conversation_id"

    def get_queryset(self):
        return Conversation.objects.for_user(self.request.user, kind=KIND_CHAT)

    def get(self, request, *args, **kwargs):
        message_id = request.GET.get("message_id")
        if not message_id:
            return HttpResponse("Missing message_id", status=400)

        self.object = self.get_object()
        conversation = self.object
        user_message = get_object_or_404(
            Message, id=message_id, conversation=conversation, is_user=True
        )
        workspace = workspace_for(request.user, KIND_CHAT)
        if not chat_ready(workspace):
            return StreamingHttpResponse(
                _sse_error_stream(
                    "unavailable",
                    "QueryMind will not run questions until you choose which tables and columns it may use.",
                ),
                content_type="text/event-stream",
            )

        messages = list(conversation.messages.all().order_by("timestamp"))
        previous_messages = messages[:-1][-6:]
        conversation_context = "\n".join(
            f"{'User' if msg.is_user else 'Assistant'}: {msg.content}"
            for msg in previous_messages
        )

        state = QueryMindState(
            question=user_message.content,
            conversation_id=conversation.id,
            message_id=user_message.id,
            connection_id=workspace.pk,
            workspace_id=workspace.pk,
            allowed_tables=list(workspace.allowed_tables or []),
            allowed_columns=dict(workspace.allowed_columns or {}),
            schema_text=workspace.schema_text or "",
            conversation_context=conversation_context,
            engine=workspace.engine,
        )

        def generate():
            STATUS_MESSAGES = {
                "planner": "Understanding your question…",
                "schema": "Looking at your data…",
                "sql_generator": "Looking at your data…",
                "sql_validator": "Checking the question is safe…",
                "explain_sql": "Checking the query plan…",
                "sql_critic": "Checking the question matches your data…",
                "sql_repair": "Checking the question is safe…",
                "sql_executor": "Fetching results…",
                "result_formatter": "Writing your answer…",
                "refuse": "Could not read that from your allowed tables…",
            }
            outcome = {}
            try:
                graph = build_on_premise_graph()
                for event in graph.stream(state):
                    first_key = next(iter(event.keys()))
                    payload = event.get(first_key) or {}
                    if isinstance(payload, dict):
                        outcome.update(payload)
                    yield _sse(
                        "status",
                        STATUS_MESSAGES.get(first_key, "Processing your request…"),
                    )

                sql = outcome.get("sql") or ""
                if sql:
                    yield _sse("sql", sql)

                execution = outcome.get("execution_result") or {}
                kind = outcome.get("answer_kind") or execution.get("kind")
                rows = execution.get("rows")
                if execution.get("success"):
                    yield _sse("rows", rows=rows or [])
                    yield _sse(
                        "meta",
                        tables=len(workspace.allowed_tables or []),
                        rows=len(rows or []),
                    )
                elif kind == "unavailable":
                    yield _sse("unavailable")
                elif kind == "zero_rows":
                    yield _sse("rows", rows=[])

                final_answer = (outcome.get("final_answer") or "").strip()
                if kind in {"unavailable", "connection_failed", "error"} and not final_answer:
                    final_answer = (
                        "QueryMind could not read that from your allowed tables."
                        if kind == "unavailable"
                        else "QueryMind could not connect to your database."
                        if kind == "connection_failed"
                        else "QueryMind could not finish this answer."
                    )

                detail = (outcome.get("database_error") or outcome.get("validation_error") or "")
                if kind in {"unavailable", "connection_failed", "error"}:
                    yield _sse(
                        "error",
                        final_answer,
                        code=kind,
                        detail=detail,
                    )
                    ConversationService.add_ai_message(conversation, final_answer)
                    yield _sse("done")
                    return

                if not final_answer:
                    yield _sse(
                        "error",
                        "QueryMind could not finish this answer. It will not invent database results.",
                        code="error",
                    )
                    return

                ai_message = ConversationService.add_ai_message(
                    conversation, final_answer
                )
                local_time = ai_message.timestamp.astimezone()
                timestamp_str = (
                    local_time.strftime("%I:%M %p").lstrip("0").replace(" 0", " ")
                )
                min_chunk_size = 3
                max_chunk_size = 8
                position = 0
                while position < len(final_answer):
                    chunk_size = random.randint(min_chunk_size, max_chunk_size)
                    token = final_answer[position : position + chunk_size]
                    position += chunk_size
                    yield _sse("result", token)
                    time.sleep(random.uniform(0.03, 0.08))
                yield _sse("done", timestamp=timestamp_str)
            except Exception as exc:
                yield _sse("error", str(exc), code="error", detail=str(exc))

        response = StreamingHttpResponse(
            generate(),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


class StreamChatView(StreamChatViewGraph):
    """Legacy alias — the graph stream is the only execution path."""


class RenderMarkdownView(LoginRequiredMixin, View):
    login_url = "login"

    def post(self, request, conversation_id):
        get_object_or_404(
            Conversation, id=conversation_id, user=request.user
        )
        try:
            data = json.loads(request.body)
            content = data.get("content", "")
            rendered = render_markdown(content)
            return HttpResponse(rendered)
        except json.JSONDecodeError:
            return JsonResponse({"error": ERROR_MESSAGES["INVALID_JSON"]}, status=400)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)


def _sse(event_type, content=None, **extra):
    payload = {"type": event_type, **extra}
    if content is not None:
        payload["content"] = content
    return f"data: {json.dumps(payload)}\n\n"


def _sse_error_stream(code, message):
    yield _sse("unavailable" if code == "unavailable" else "error", message, code=code)
    yield _sse("done")
