from connections.services.prompt import PromptGenerator
from connections.services.prompt import PromptGenerator
import traceback
import httpx
import json
from connections.services.result_prompt import SQLResultPromptGenerator
from google import genai
import os
import traceback
from google import genai
from google.genai import types
import re
from rest_framework import status
from rest_framework.response import Response
from chat.constants import ERROR_MESSAGES, OLLAMA_CHAT_ENDPOINT, OLLAMA_MODEL


class ChatService:

    @staticmethod
    def process_message(
        conversation,
        user_message,
    ):
        # -----------------------------------------
        # 1. Build conversation context
        # -----------------------------------------

        messages = list(conversation.messages.all().order_by("timestamp"))

        previous_messages = messages[:-1][-6:]

        conversation_context = "\n".join(
            f"{'User' if msg.is_user else 'Assistant'}: {msg.content}"
            for msg in previous_messages
        )

        # -----------------------------------------
        # 2. Generate SQL prompt
        # -----------------------------------------

        prompt_generator = PromptGenerator()

        prompt = prompt_generator.generate(
            question=user_message.content,
            schema="",
            conversation_context=conversation_context,
        )

        print("The prompt is : ", prompt)

        # -----------------------------------------
        # 3. Ask Qwen for SQL
        # -----------------------------------------

        sql = ChatService.ask_ai(prompt)

        sql = sql.strip()

        if not sql:
            raise ValueError("AI returned an empty SQL query.")

        # -----------------------------------------
        # 4. Validate SQL
        # -----------------------------------------

        # executor = ReadOnlySQLExecutor(
        #     database="client",
        # )

        # executor.validate(sql)

        # -----------------------------------------
        # 5. Execute SQL
        # -----------------------------------------

        # rows = []

        # for row in executor.stream(sql):
        #     rows.append(row)

        # -----------------------------------------
        # 6. Generate answer prompt
        # -----------------------------------------

        # answer_prompt_generator = SQLResultPromptGenerator()

        # answer_prompt = answer_prompt_generator.generate(
        #     user_question=user_message.content,
        #     sql=sql,
        #     rows=rows,
        # )

        # -----------------------------------------
        # 7. Ask Qwen for final answer
        # -----------------------------------------

        # final_answer = ChatService.ask_ai(answer_prompt)

        # final_answer = final_answer.strip()

        # -----------------------------------------
        # 8. Save AI message
        # -----------------------------------------

        # ai_message = ConversationService.add_ai_message(
        #     conversation,
        #     final_answer,
        # )

        return {
            "sql": sql,
            # "rows": rows,
            # "answer": final_answer,
            # "ai_message": ai_message,
        }

    @staticmethod
    def process_Result(
        conversation,
        user_message,
        result,
    ):
        # -----------------------------------------
        # 1. Build conversation context
        # -----------------------------------------

        # messages = list(conversation.messages.all().order_by("timestamp"))

        # previous_messages = messages[:-1][-6:]

        # conversation_context = "\n".join(
        #     f"{'User' if msg.is_user else 'Assistant'}: {msg.content}"
        #     for msg in previous_messages
        # )

        # -----------------------------------------
        # 2. Generate SQL prompt
        # -----------------------------------------

        # prompt_generator = PromptGenerator()

        # prompt = prompt_generator.generate(
        #     question=user_message.content,
        #     conversation_context=conversation_context,
        # )

        # -----------------------------------------
        # 3. Ask Qwen for SQL
        # -----------------------------------------

        # sql = ChatService.ask_ai(prompt)

        # sql = sql.strip()

        # if not sql:
        #     raise ValueError("AI returned an empty SQL query.")

        # -----------------------------------------
        # 4. Validate SQL
        # -----------------------------------------

        # executor = ReadOnlySQLExecutor(
        #     database="client",
        # )

        # executor.validate(sql)

        # -----------------------------------------
        # 5. Execute SQL
        # -----------------------------------------

        # rows = []

        # for row in executor.stream(sql):
        #     rows.append(row)

        # -----------------------------------------
        # 6. Generate answer prompt
        # -----------------------------------------

        answer_prompt_generator = SQLResultPromptGenerator()

        answer_prompt = answer_prompt_generator.generate(
            user_question=user_message,
            sql="",
            rows=result,
        )

        # -----------------------------------------
        # 7. Ask Qwen for final answer
        # -----------------------------------------

        final_answer = ChatService.ask_ai(answer_prompt)

        final_answer = final_answer.strip()

        # -----------------------------------------
        # 8. Save AI message
        # -----------------------------------------

        # ai_message = ConversationService.add_ai_message(
        #     conversation,
        #     final_answer,
        # )

        return {
            # "sql": sql,
            # "rows": rows,
            "answer": final_answer,
            # "ai_message": ai_message,
        }

    # @staticmethod
    # def ask_ai(prompt):
    #     with httpx.Client(timeout=60.0) as client:
    #         response = client.post(
    #             OLLAMA_CHAT_ENDPOINT,
    #             json={
    #                 "model": OLLAMA_MODEL,
    #                 "messages": [
    #                     {
    #                         "role": "user",
    #                         "content": prompt,
    #                     }
    #                 ],
    #                 "stream": False,
    #             },
    #         )

    #         response.raise_for_status()

    #         data = response.json()

    #         return data["message"]["content"]

    # @staticmethod
    # def ask_ai(prompt: str) -> str:
    #     client = genai.Client()

    #     interaction = client.interactions.create(model="gemini-3.7-flash", input=prompt)
    #     # Navigate Gemini's specific response hierarchy
    #     print("The interaction is : ", interaction)
    #     return interaction.output_text

    # @staticmethod
    # def ask_ai(prompt: str) -> str:
    #     try:
    #         print("Request came to ai: ")
    #         # return "Thanks for asking"
    #         api_key = os.getenv("GEMINI_API_KEY")
    #         print("THe api key is : ", api_key)
    #         # return "thanks"
    #         client = genai.Client(api_key=api_key)

    #         interaction = client.interactions.create(
    #             model="gemini-3.7-flash",
    #             input=prompt,
    #         )

    #         print("The interaction is:", interaction)

    #         return interaction.output_text

    #     except Exception as e:
    #         print("AI request failed:")
    #         print(f"Error type: {type(e).__name__}")
    #         print(f"Error message: {e}")
    #         traceback.print_exc()

    #         return "Sorry, I couldn't process your request right now. Please try again later."

    @staticmethod
    def ask_ai(prompt: str) -> str:
        try:
            print("Request came to ai:")
            api_key = os.getenv("GEMINI_API_KEY")
            print("GEMINI_API_KEY : ", api_key)
            # 1. Increase read timeout to 30s to allow headroom for model generation
            client = genai.Client(
                api_key=api_key,
            )
            # http_options=types.HttpOptions(timeout=30000),  # 30 seconds in ms

            # 2. Stream response chunks to keep socket active
            response_stream = client.models.generate_content_stream(
                model="gemini-3.6-flash",
                contents=prompt,
            )

            # Accumulate text chunks as they arrive over the wire
            full_text = "".join(chunk.text for chunk in response_stream if chunk.text)
            return full_text

        except Exception as e:
            print("AI request failed:")
            print(f"Error type: {type(e).__name__}")
            print(f"Error message: {e}")
            traceback.print_exc()

            return "Sorry, I couldn't process your request right now. Please try again later."

    @staticmethod
    def ask_on_premise_ai(prompt: str) -> str:
        try:
            # print("Request came on premis AI, and prompt is :", prompt)

            full_response = ""

            # Use synchronous HTTP client with streaming
            with httpx.Client(timeout=100.0) as client:
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

                    response.raise_for_status()

                    for line in response.iter_lines():
                        if not line:
                            continue

                        try:
                            data = json.loads(line)

                            if "message" in data and "content" in data["message"]:
                                token = data["message"]["content"]
                                full_response += token

                        except json.JSONDecodeError:
                            continue
            # print("The full response is : ", full_response)
            return full_response

        except Exception as e:
            print("AI request failed:")
            print(f"Error type: {type(e).__name__}")
            print(f"Error message: {e}")
            traceback.print_exc()

            return "Sorry, I couldn't process your request right now. Please try again later."

    staticmethod

    def process_user_query(generated_sql: str) -> dict:
        # Handle explicit out-of-scope responses from Text-to-SQL
        if not generated_sql or "SELECT NULL" in generated_sql.upper():
            return {
                "status": "out_of_scope",
                "message": "I couldn't find subscription details in your store database. Subscription and billing information are managed under your main account billing settings.",
            }

        # Execute valid SQL query against tenant database...
        return generated_sql

    @staticmethod
    def ask_ai2(prompt: str) -> str:
        try:
            print("Request came to ai 2: ")
            api_key = os.getenv("GEMINI_API_KEY")

            # 1. Enforce strict HTTP transport timeout (e.g., 10 seconds)
            client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=10000),  # Timeout in ms
            )

            # 2. Configure interaction for low thinking latency & stateless execution
            interaction = client.interactions.create(
                model="gemini-3.7-flash",
                input=prompt,
                store=False,  # Disable server-side state allocation for faster single-turn calls
                generation_config={
                    "thinking_level": "low"  # Bypass extended multi-step thought loops
                },
            )

            print("The interaction is:", interaction)
            return interaction.output_text

        except Exception as e:
            print("AI request failed:")
            print(f"Error type: {type(e).__name__}")
            print(f"Error message: {e}")
            traceback.print_exc()

            return "Sorry, I couldn't process your request right now. Please try again later."


import re


class SQLFallbackInterceptor:
    # Improved regex patterns to capture alias variations (e.g. AS subscription_plan)
    SENTINEL_PATTERNS = [
        r"^SELECT\s+(NULL|0|FALSE|'N/A'|'UNANSWERABLE')(\s+AS\s+[a-zA-Z0-9_]+)?\s*;?$",
        r"^SELECT\s+.*WHERE\s+1\s*=\s*0",
        r"LIMIT\s+0\s*;?$",
        r"^SELECT\s+CURRENT_DATE(\s+AS\s+[a-zA-Z0-9_]+)?\s*;?$",
    ]

    @classmethod
    def analyze_query(cls, sql: str, allowed_tables: set) -> tuple[bool, str]:
        if not sql or not sql.strip():
            return True, "Empty SQL query returned from AI."

        # Normalize spaces and convert to uppercase for regex checking
        clean_sql = re.sub(r"\s+", " ", sql.strip().upper())

        # 1. Check if the query matches a sentinel expression (with or without alias)
        for pattern in cls.SENTINEL_PATTERNS:
            if re.search(pattern, clean_sql, re.IGNORECASE):
                return True, "Out-of-scope question (sentinel expression detected)."

        # 2. Verify that query references valid tables (or catches missing FROM clauses)
        # extracted_tables = set(
        #     re.findall(r"(?:FROM|JOIN)\s+`?([a-zA-Z0-9_]+)`?", clean_sql, re.IGNORECASE)
        # )

        # # If there are no tables (e.g. SELECT NULL;) or hallucinated tables, flag it
        # if not extracted_tables:
        #     return True, "Query does not target any schema tables."

        # hallucinated_tables = extracted_tables - allowed_tables
        # if hallucinated_tables:
        #     return (
        #         True,
        #         f"Referenced non-existent tables: {', '.join(hallucinated_tables)}",
        #     )

        return False, "Query is valid."


# Define allowed tables from your schema
ALLOWED_TENANT_TABLES = {
    "users",
    "password_reset_tokens",
    "sessions",
    "cache",
    "cache_locks",
    "jobs",
    "job_batches",
    "failed_jobs",
    "categories",
    "products",
    "product_images",
    "product_variants",
    "product_variant_options",
    "product_details",
    "orders",
    "order_items",
    "promo_codes",
    "shop_settings",
    "shop_policies",
    "shop_chat_settings",
    "shop_social_links",
    "shop_sms_settings",
    "shop_sms_templates",
    "shop_marketing_settings",
    "receipt_counters",
}


def build_chat_response(conversation, user_message, result, created):
    print("Inside build_chat_respons ", conversation, user_message, result, created)
    raw_sql = result.get("sql", "")

    # Analyze generated SQL against tenant schema boundaries
    is_fallback, fallback_reason = SQLFallbackInterceptor.analyze_query(
        sql=raw_sql, allowed_tables=ALLOWED_TENANT_TABLES
    )

    if is_fallback:
        return Response(
            {
                "user_id": conversation.user_id,
                "tenant_id": conversation.tenant_id,
                "user_message_id": user_message.id,
                "sql": None,
                "is_executable": False,
                "conversation_created": created,
                "error": {
                    "code": "OUT_OF_SCHEMA_SCOPE",
                    # "message": "The requested information (e.g., subscriptions) is not available in the store database schema.",
                    "details": fallback_reason,
                },
            },
            status=status.HTTP_200_OK,
        )

    # Valid, executable SQL query response
    return Response(
        {
            "user_id": conversation.user_id,
            "tenant_id": conversation.tenant_id,
            "user_message_id": user_message.id,
            "sql": raw_sql,
            "is_executable": True,
            "conversation_created": created,
            "error": None,
        },
        status=status.HTTP_200_OK,
    )
