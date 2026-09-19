from typing import Any

from agent.llm import ask_state
from agent.state import QueryMindState

FALLBACK = (
    "I'm QueryMind. I answer questions from the tables you allowed. "
    "Ask about your data whenever you're ready."
)


def converse_answer(state: QueryMindState) -> dict[str, Any]:
    prompt = f"""
You are QueryMind, a read-only data assistant. The user is making conversation, not asking for database results.
Reply briefly and helpfully. Do not invent table data. Do not write SQL.
If they want numbers or records, invite them to ask about the tables they allowed.

CONVERSATION:
{state.conversation_context or "None"}

USER:
{state.question}
""".strip()
    try:
        answer = (ask_state(state, prompt) or "").strip()
    except Exception:
        answer = FALLBACK
    if not answer:
        answer = FALLBACK
    return {
        "final_answer": answer,
        "answer_kind": "conversation",
        "execution_mode": "converse",
        "routing": {
            **(state.routing or {}),
            "mode": "converse",
            "operation": None,
            "sql_fallback": False,
            "reason": "conversation",
        },
        "current_node": "converse",
        "status": "completed",
    }
