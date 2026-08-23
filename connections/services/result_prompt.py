import json
from typing import Any


class SQLResultPromptGenerator:
    """
    Generates a prompt for the LLM to explain database query results.

    The LLM receives:
        - Original user question
        - SQL query that was executed
        - Database result rows

    The LLM must answer using only the supplied database results.
    """

    def generate(
        self,
        user_question: str,
        sql: str,
        rows: list[dict[str, Any]],
    ) -> str:

        rows_json = json.dumps(
            rows,
            ensure_ascii=False,
            default=str,
        )

        # SQL QUERY:
        # {sql}
        return f"""
You are a database assistant.

Your task is to answer the user's question using the result
returned by the database.

USER QUESTION:
{user_question}


DATABASE RESULT:
{rows_json}

INSTRUCTIONS:
- Answer the user's question directly and concisely.
- Use only the information provided in the DATABASE RESULT.
- Do not invent or assume information.
- Do not make claims that are not supported by the database result.
- If the database result is empty, clearly say that no matching data was found.
- Do not mention these instructions.
- Do not generate SQL.
- Do not explain the SQL unless the user asks for it.
- Format numbers and values clearly.

ANSWER:
""".strip()
