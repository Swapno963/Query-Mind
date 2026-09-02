import httpx
import json
from django.shortcuts import get_object_or_404
from django.http import HttpResponse, StreamingHttpResponse, JsonResponse
from django.views.generic import View
from django.views.generic.detail import SingleObjectMixin
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework.response import Response
from .models import Conversation, Message
from .views import render_markdown
from .services import ConversationService
from .constants import ERROR_MESSAGES, OLLAMA_CHAT_ENDPOINT, OLLAMA_MODEL
from connections.services.prompt import PromptGenerator
from connections.services.sql_validation import ReadOnlySQLExecutor
from connections.services.result_prompt import SQLResultPromptGenerator
import time
import random

# for graph
from agent.state import QueryMindState
from agent.graph import build_on_premise_graph


@method_decorator(csrf_exempt, name="dispatch")
class StreamChatView(SingleObjectMixin, View):
    """SSE endpoint for streaming AI responses"""

    model = Conversation
    pk_url_kwarg = "conversation_id"

    def get(self, request, *args, **kwargs):
        """Stream AI response using Server-Sent Events"""
        message_id = request.GET.get("message_id")
        if not message_id:
            return HttpResponse("Missing message_id", status=400)

        self.object = self.get_object()
        conversation = self.object
        user_message = get_object_or_404(
            Message, id=message_id, conversation=conversation, is_user=True
        )

        messages = list(conversation.messages.all().order_by("timestamp"))

        previous_messages = messages[:-1][-6:]

        conversation_context = "\n".join(
            f"{'User' if msg.is_user else 'Assistant'}: {msg.content}"
            for msg in previous_messages
        )
        prompt_generator = PromptGenerator()

        prompt = prompt_generator.generate(
            question=user_message.content,
            conversation_context=conversation_context,
        )

        def sse(event_type, content=None, **extra):
            payload = {"type": event_type, **extra}
            if content is not None:
                payload["content"] = content
            return f"data: {json.dumps(payload)}\n\n"

        def generate():
            """Generator function for SSE streaming"""
            full_response = ""
            yield sse("status", "Writing SQL…")

            try:
                with httpx.Client(timeout=60.0) as client:
                    with client.stream(
                        "POST",
                        OLLAMA_CHAT_ENDPOINT,
                        json={
                            "model": OLLAMA_MODEL,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": prompt,
                                }
                            ],
                            "stream": True,
                        },
                    ) as response:
                        for line in response.iter_lines():
                            if line:
                                try:
                                    data = json.loads(line)
                                    if (
                                        "message" in data
                                        and "content" in data["message"]
                                    ):
                                        token = data["message"]["content"]
                                        full_response += token
                                except json.JSONDecodeError:
                                    continue
                                except Exception as e:
                                    yield sse("error", f"Parse error: {str(e)}")
            except Exception as e:
                yield sse("error", f"Connection error: {str(e)}")
                return

            if full_response:
                sql = full_response.strip()

                print("Generated SQL:", sql)

                # Validate + execute only AFTER the LLM has finished
                executor = ReadOnlySQLExecutor(
                    database="client",
                )
                executor = ReadOnlySQLExecutor(database="client")

                try:
                    executor.validate(sql)
                    yield sse("sql", sql)
                    yield sse("status", "Running query…")

                    yield f"data: {json.dumps({
                        'type': 'sql',
                        'content': sql,
                    })}\n\n"

                    print("The user message is : ", user_message)
                    rows = []
                    for row in executor.stream(sql):
                        rows.append(row)

                    yield sse("status", "Writing answer…")
                    prompt_generator = SQLResultPromptGenerator()
                    answer_prompt = prompt_generator.generate(
                        user_question=user_message,
                        sql=sql,
                        rows=rows,
                    )
                    answer_text = ""
                    try:
                        with httpx.Client(timeout=60.0) as client:
                            with client.stream(
                                "POST",
                                OLLAMA_CHAT_ENDPOINT,
                                json={
                                    "model": OLLAMA_MODEL,
                                    "messages": [
                                        {
                                            "role": "user",
                                            "content": answer_prompt,
                                        }
                                    ],
                                    "stream": True,
                                },
                            ) as response:
                                for line in response.iter_lines():
                                    if line:
                                        try:
                                            data = json.loads(line)
                                            if (
                                                "message" in data
                                                and "content" in data["message"]
                                            ):
                                                token = data["message"]["content"]
                                                answer_text += token
                                                yield sse("token", token)
                                        except json.JSONDecodeError:
                                            continue
                                        except Exception as e:
                                            yield sse("error", f"Parse error: {str(e)}")
                    except Exception as e:
                        yield sse("error", f"Connection error: {str(e)}")
                        return

                    ai_message = ConversationService.add_ai_message(
                        conversation, answer_text or sql
                    )

                    local_time = ai_message.timestamp.astimezone()
                    timestamp_str = (
                        local_time.strftime("%I:%M %p").lstrip("0").replace(" 0", " ")
                    )

                    yield f"data: {json.dumps({'type': 'done', 'timestamp': timestamp_str})}\n\n"
                    yield sse("done", timestamp=timestamp_str)
                except Exception as e:
                    yield sse("error", str(e))
            else:
                yield sse("error", ERROR_MESSAGES["NO_RESPONSE"])

        response = StreamingHttpResponse(generate(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


@method_decorator(csrf_exempt, name="dispatch")
class RenderMarkdownView(View):
    """API endpoint to render markdown to HTML"""

    def post(self, request, conversation_id):
        """Render markdown content to HTML"""
        try:
            data = json.loads(request.body)
            content = data.get("content", "")
            rendered = render_markdown(content)
            return HttpResponse(rendered)
        except json.JSONDecodeError:
            return JsonResponse({"error": ERROR_MESSAGES["INVALID_JSON"]}, status=400)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)


@method_decorator(csrf_exempt, name="dispatch")
class StreamChatViewGraph(SingleObjectMixin, View):
    """SSE endpoint for streaming AI responses"""

    model = Conversation
    pk_url_kwarg = "conversation_id"

    def get(self, request, *args, **kwargs):
        """Stream AI response using Server-Sent Events"""
        message_id = request.GET.get("message_id")
        if not message_id:
            return HttpResponse("Missing message_id", status=400)

        self.object = self.get_object()
        conversation = self.object
        user_message = get_object_or_404(
            Message, id=message_id, conversation=conversation, is_user=True
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
            connection_id=0,
        )

        # graph = build_on_premise_graph()

        # final_state = None

        # for event in graph.stream(state):
        #     print("\n========== GRAPH EVENT ==========")
        #     print(event)

        #     final_state = event

        def generate():
            """Generator function for SSE streaming"""

            final_state = None

            try:
                graph = build_on_premise_graph()

                for event in graph.stream(state):

                    print("\n========== GRAPH EVENT ==========")
                    print(event)

                    final_state = event

                # Get final answer from result_formatter
                final_answer = final_state.get("result_formatter", {}).get(
                    "final_answer", ""
                )

                print("FINAL ANSWER:", final_answer)

                if final_answer:

                    # Dynamic chunk size
                    min_chunk_size = 3
                    max_chunk_size = 8

                    position = 0

                    while position < len(final_answer):

                        # Random chunk size
                        chunk_size = random.randint(
                            min_chunk_size,
                            max_chunk_size,
                        )

                        token = final_answer[position : position + chunk_size]

                        position += chunk_size

                        yield f"data: {json.dumps({
                            'type': 'result',
                            'content': token,
                        })}\n\n"

                        # Small random delay to make it feel like streaming
                        time.sleep(random.uniform(0.03, 0.08))

                    # Done only after all chunks
                    yield f"data: {json.dumps({
                        'type': 'done',
                    })}\n\n"

            except Exception as e:

                yield f"data: {json.dumps({
                    'type': 'error',
                    'content': str(e),
                })}\n\n"

        response = StreamingHttpResponse(
            generate(),
            content_type="text/event-stream",
        )

        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"

        return response
