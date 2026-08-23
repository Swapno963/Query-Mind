import json
import httpx

from django.conf import settings

from ..models import Message
from ..services import ConversationService
from connections.services.prompt import PromptGenerator
from connections.services.prompt import PromptGenerator

from connections.services.result_prompt import SQLResultPromptGenerator
from connections.services.sql_validation import ReadOnlySQLExecutor
from google import genai

from chat.constants import (
    ERROR_MESSAGES,
    OLLAMA_CHAT_ENDPOINT,
    OLLAMA_MODEL,
    GEMINI_API_KEY,
)


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

    @staticmethod
    def ask_ai(prompt: str) -> str:
        api_key = GEMINI_API_KEY
        # if not api_key:
        #     raise ValueError("GEMINI_API_KEY environment variable is missing.")

        # # Using the fast, cost-effective flash model; can be swapped to gemini-3.7-flash
        # url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        # with httpx.Client(timeout=60.0) as client:
        #     response = client.post(
        #         url, json={"contents": [{"parts": [{"text": prompt}]}]}
        #     )

        #     response.raise_for_status()
        #     data = response.json()
        client = genai.Client()

        interaction = client.interactions.create(model="gemini-3.7-flash", input=prompt)
        # Navigate Gemini's specific response hierarchy
        print("The interaction is : ", interaction)
        return interaction.output_text
