"""Pick local Ollama or online Gemini from org/state backend."""

from chat.api.chat_service import ChatService


def ask_llm(prompt: str, *, backend: str = "local", **kwargs) -> str:
    return ChatService.ask_for_backend(prompt, backend or "local", **kwargs)


def ask_state(state, prompt: str, **kwargs) -> str:
    backend = getattr(state, "llm_backend", None) or "local"
    return ask_llm(prompt, backend=backend, **kwargs)
