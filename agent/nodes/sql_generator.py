# Generates SQL
# Execute SQL

# agent/nodes/sql_generator.py

import json
from typing import Any

import httpx

from ..state import QueryMindState

from connections.services.prompt import PromptGenerator
from chat.constants import OLLAMA_CHAT_ENDPOINT, OLLAMA_MODEL
from chat.api.chat_service import ChatService


def sql_generator(state: QueryMindState) -> dict[str, Any]:
    """
    Generate SQL from the user's question and discovered schema.

    Responsibilities:
    - Build SQL-generation prompt
    - Call LLM
    - Collect the complete LLM response
    - Store generated SQL in state

    Does NOT:
    - validate SQL
    - execute SQL
    - repair SQL
    - analyze errors
    - persist Django models
    - stream SSE events
    - generate the final answer
    """
    print("Came to sql generator")

    question = state.question.strip()

    if not question:
        return {
            "database_error": "Question cannot be empty.",
            "current_node": "sql_generator",
            "status": "failed",
        }

    try:
        # ========================================================
        # 1. Generate prompt
        # ========================================================

        prompt_generator = PromptGenerator()

        prompt = prompt_generator.generate(
            question=question,
            conversation_context=state.conversation_context,
            # schema=state.schema,
        )

        # ========================================================
        # 2. Ask LLM to generate SQL
        # ========================================================

        sql = ChatService.ask_ai(prompt)

        # sql = sql.strip()

        # ========================================================
        # 3. Make sure we actually received SQL
        # ========================================================

        if not sql:
            return {
                "database_error": "LLM returned an empty SQL query.",
                "current_node": "sql_generator",
                "status": "failed",
            }

        # ========================================================
        # 4. Update graph state
        # ========================================================

        return {
            "sql": sql,
            "sql_attempts": state.sql_attempts + 1,
            "database_error": None,
            "current_node": "sql_generator",
            "status": "running",
        }

    except httpx.HTTPError as exc:
        print("error : ", exc)
        return {
            "database_error": f"LLM request failed: {exc}",
            "current_node": "sql_generator",
            "status": "failed",
        }

    except Exception as exc:
        print("error : ", exc)

        return {
            "database_error": str(exc),
            "current_node": "sql_generator",
            "status": "failed",
        }


def sql_generator_on_premise(state: QueryMindState) -> dict[str, Any]:
    """
    Generate SQL from the user's question and discovered schema.

    Responsibilities:
    - Build SQL-generation prompt
    - Call LLM
    - Collect the complete LLM response
    - Store generated SQL in state

    Does NOT:
    - validate SQL
    - execute SQL
    - repair SQL
    - analyze errors
    - persist Django models
    - stream SSE events
    - generate the final answer
    """
    print("Came to sql on premise generator")

    question = state.question.strip()

    if not question:
        return {
            "database_error": "Question cannot be empty.",
            "current_node": "sql_generator",
            "status": "failed",
        }

    try:
        # ========================================================
        # 1. Generate prompt
        # ========================================================

        prompt_generator = PromptGenerator()

        prompt = prompt_generator.generate(
            question=question,
            conversation_context=state.conversation_context,
            # schema=state.schema,
        )

        # ========================================================
        # 2. Ask LLM to generate SQL
        # ========================================================

        sql = ChatService.ask_on_premise_ai(prompt)

        # sql = sql.strip()

        # ========================================================
        # 3. Make sure we actually received SQL
        # ========================================================

        if not sql:
            return {
                "database_error": "LLM returned an empty SQL query.",
                "current_node": "sql_generator",
                "status": "failed",
            }

        # ========================================================
        # 4. Update graph state
        # ========================================================

        return {
            "sql": sql,
            "sql_attempts": state.sql_attempts + 1,
            "database_error": None,
            "current_node": "sql_generator",
            "status": "running",
        }

    except httpx.HTTPError as exc:
        print("error : ", exc)
        return {
            "database_error": f"LLM request failed: {exc}",
            "current_node": "sql_generator",
            "status": "failed",
        }

    except Exception as exc:
        print("error : ", exc)

        return {
            "database_error": str(exc),
            "current_node": "sql_generator",
            "status": "failed",
        }


def _generate_sql_from_ollama(prompt: str) -> str:
    """
    Call Ollama and collect the complete streamed response.

    This function does not know anything about QueryMind state,
    graph routing, SQL validation, or database execution.
    """

    full_response = ""

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

            response.raise_for_status()

            for line in response.iter_lines():

                if not line:
                    continue

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                message = data.get("message")

                if not message:
                    continue

                content = message.get("content")

                if content:
                    full_response += content

    return full_response
