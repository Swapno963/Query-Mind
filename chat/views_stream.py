import json
import logging
import random
import time

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponse, StreamingHttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.generic import View
from django.views.generic.detail import SingleObjectMixin

from langgraph.errors import GraphRecursionError

from agent.graph import GRAPH_RUN_CONFIG, build_on_premise_graph, build_online_graph
from agent.nodes.result_formatter import deterministic_result_answer
from agent.state import QueryMindState
from chat.authentication import mcp_headers_for_user
from chat.organizations import mcp_server_url_for, organization_for
from chat.product import org_chat_enabled, org_llm_backend
from chat.ui import KIND_CHAT, chat_ready, workspace_for

from .constants import ERROR_MESSAGES
from .models import Conversation, Message
from .services import ConversationService
from .views import render_markdown

logger = logging.getLogger("querymind")


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
        org = organization_for(request.user)
        if not org_chat_enabled(org):
            return HttpResponse("This organization does not use chat.", status=403)
        mcp_url = mcp_server_url_for(request.user)
        if not chat_ready(workspace) and not mcp_url:
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
        backend = org_llm_backend(org)

        state = QueryMindState(
            question=user_message.content,
            conversation_id=conversation.id,
            message_id=user_message.id,
            connection_id=workspace.pk if workspace else 0,
            workspace_id=workspace.pk if workspace else None,
            allowed_tables=list((workspace.allowed_tables if workspace else None) or []),
            allowed_columns=dict((workspace.allowed_columns if workspace else None) or {}),
            schema_text=(workspace.schema_text if workspace else "") or "",
            conversation_context=conversation_context,
            engine=workspace.engine if workspace else "postgres",
            mcp_server_url=mcp_url,
            mcp_headers=mcp_headers_for_user(request.user, request),
            llm_backend=backend,
            product_surface="chat",
        )

        def generate():
            STATUS_MESSAGES = {
                "classify_operation": "Understanding what you want to do…",
                "converse": "Replying…",
                "policy_check": "Checking what QueryMind is allowed to do…",
                "capability_resolve": "Checking available tools…",
                "mcp_execute": "Running a business operation…",
                "planner": "Understanding your question…",
                "schema": "Choosing which tables to use…",
                "sql_generator": "Writing a lookup…",
                "sql_validator": "Checking the question is safe…",
                "explain_sql": "Checking the query plan…",
                "sql_critic": "Checking the question matches your data…",
                "sql_repair": "Fixing the lookup…",
                "sql_executor": "Fetching results…",
                "result_formatter": "Writing your answer…",
                "refuse": "Could not complete that request…",
            }
            outcome = {}
            emitted_sql = False
            emitted_rows = False
            started = time.monotonic()
            success = False
            try:
                graph = (
                    build_on_premise_graph()
                    if backend == "local"
                    else build_online_graph()
                )
                for event in graph.stream(state, config=GRAPH_RUN_CONFIG):
                    first_key = next(iter(event.keys()))
                    payload = event.get(first_key) or {}
                    if isinstance(payload, dict):
                        outcome.update(payload)
                    status = STATUS_MESSAGES.get(first_key)
                    if status:
                        yield _sse("status", status)
                    if first_key == "sql_executor" and isinstance(payload, dict):
                        sql = payload.get("sql") or outcome.get("sql") or ""
                        if sql and not emitted_sql:
                            yield _sse("sql", sql)
                            emitted_sql = True
                        execution = payload.get("execution_result") or {}
                        if execution.get("success") and not emitted_rows:
                            rows = execution.get("rows") or []
                            yield _sse("rows", rows=rows)
                            yield _sse(
                                "meta",
                                tables=len((workspace.allowed_tables if workspace else None) or []),
                                rows=len(rows),
                            )
                            emitted_rows = True

                sql = outcome.get("sql") or ""
                if sql and outcome.get("answer_kind") != "conversation" and not emitted_sql:
                    yield _sse("sql", sql)
                    emitted_sql = True

                execution = outcome.get("execution_result") or {}
                kind = outcome.get("answer_kind") or execution.get("kind")
                rows = execution.get("rows")
                if execution.get("success") and not emitted_rows:
                    yield _sse("rows", rows=rows or [])
                    yield _sse(
                        "meta",
                        tables=len((workspace.allowed_tables if workspace else None) or []),
                        rows=len(rows or []),
                    )
                    emitted_rows = True
                elif kind == "unavailable":
                    yield _sse("unavailable")
                elif kind == "zero_rows" and not emitted_rows:
                    yield _sse("rows", rows=[])
                    emitted_rows = True

                final_answer = (outcome.get("final_answer") or "").strip()
                if not final_answer and execution.get("success"):
                    final_answer = deterministic_result_answer(rows or [])
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
                success = True
            except GraphRecursionError:
                yield _sse(
                    "error",
                    "QueryMind could not finish this answer. Try asking again in a moment.",
                    code="error",
                    detail="The lookup retried too many times.",
                )
            except Exception as exc:
                yield _sse(
                    "error",
                    "QueryMind could not finish this answer. Try asking again in a moment.",
                    code="error",
                    detail=_public_error_detail(exc),
                )
            finally:
                _log_chat_stream(request, conversation, outcome, started, success=success)

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
    return f"data: {json.dumps(payload, cls=DjangoJSONEncoder)}\n\n"


def _public_error_detail(exc: Exception) -> str:
    message = str(exc)
    if "JSON serializable" in message or "Object of type" in message:
        return ""
    if len(message) > 180:
        return ""
    return message


def _log_chat_stream(request, conversation, outcome, started, *, success):
    routing = outcome.get("routing") or {}
    logger.info(
        "chat stream conversation_id=%s user_id=%s mode=%s tool=%s reason=%s duration_ms=%s retry_count=%s success=%s",
        getattr(conversation, "id", None),
        getattr(request.user, "id", None),
        routing.get("mode") or outcome.get("execution_mode") or "",
        routing.get("tool") or "",
        routing.get("reason") or "",
        int((time.monotonic() - started) * 1000),
        outcome.get("retry_count") or 0,
        success,
    )


def _sse_error_stream(code, message):
    yield _sse("unavailable" if code == "unavailable" else "error", message, code=code)
    yield _sse("done")
