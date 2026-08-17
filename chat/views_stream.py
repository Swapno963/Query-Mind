import httpx
import json
from django.shortcuts import get_object_or_404
from django.http import HttpResponse, StreamingHttpResponse, JsonResponse
from django.views.generic import View
from django.views.generic.detail import SingleObjectMixin
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from .models import Conversation, Message
from .views import render_markdown
from .services import ConversationService
from .constants import ERROR_MESSAGES, OLLAMA_CHAT_ENDPOINT, OLLAMA_MODEL
from connections.services.prompt import PromptGenerator
from connections.services.sql_validation import ReadOnlySQLExecutor


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

        # Build conversation context
        # messages = list(conversation.messages.all().order_by("timestamp"))
        # ollama_messages = []
        # for msg in messages[-10:]:
        #     role = "user" if msg.is_user else "assistant"
        #     ollama_messages.append({"role": role, "content": msg.content})

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
        # print("The full prompt is : ", prompt)

        def generate():
            """Generator function for SSE streaming"""
            full_response = ""

            try:
                # Use synchronous httpx client with stream
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
                            # print("OLLAMA RAW:", repr(line))

                            if line:
                                try:
                                    data = json.loads(line)
                                    # print("OLLAMA JSON:", data)
                                    if (
                                        "message" in data
                                        and "content" in data["message"]
                                    ):
                                        token = data["message"]["content"]
                                        full_response += token
                                        yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
                                except json.JSONDecodeError:
                                    continue
                                except Exception as e:
                                    yield f"data: {json.dumps({'type': 'error', 'content': f'Parse error: {str(e)}'})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'content': f'Connection error: {str(e)}'})}\n\n"
                return

            # new code
            if full_response:
                sql = full_response.strip()

                print("Generated SQL:", sql)

                # Validate + execute only AFTER the LLM has finished
                executor = ReadOnlySQLExecutor(
                    database="client",
                    allowed_tables={
                        "students",
                        "teachers",
                        "branches",
                        "courses",
                    },
                )

                try:
                    executor.validate(sql)

                    yield f"data: {json.dumps({
                        'type': 'sql',
                        'content': sql,
                    })}\n\n"

                    yield f"data: {json.dumps({
                        'type': 'query_started','content':'Running sql query to the database.'
                    })}\n\n"

                    for row in executor.stream(sql):
                        yield f"data: {json.dumps({
                            'type': 'row',
                            'content': row,
                        })}\n\n"

                    yield f"data: {json.dumps({
                        'type': 'query_completed','content':'Query run successfully.'
                    })}\n\n"

                    # Save the complete message if we got a response
                    # if full_response:
                    #     print("Full response is : ", full_response)
                    ai_message = ConversationService.add_ai_message(
                        conversation, full_response
                    )
                    #     print("Ai message is : ", ai_message)
                    #     # Send completion signal
                    #     # Convert to local timezone and format to match Django templates (g:i A format)
                    local_time = ai_message.timestamp.astimezone()
                    timestamp_str = (
                        local_time.strftime("%I:%M %p").lstrip("0").replace(" 0", " ")
                    )
                    yield f"data: {json.dumps({'type': 'done', 'timestamp': timestamp_str})}\n\n"
                # else:
                #     yield f"data: {json.dumps({'type': 'error', 'content': ERROR_MESSAGES['NO_RESPONSE']})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({
                        'type': 'error',
                        'content': str(e),
                    })}\n\n"

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
