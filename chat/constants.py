"""Constants and configuration for the chat application"""

import os

# Ollama API Configuration
# Docker/EC2 localhost is the host machine, not a compose service.
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_CHAT_ENDPOINT = f"{OLLAMA_BASE_URL}/api/chat"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "100"))
OLLAMA_STREAM_TIMEOUT = 60.0


# Message Configuration
MAX_MESSAGE_LENGTH = 10000
CONVERSATION_CONTEXT_LIMIT = 10  # Number of previous messages to include
TITLE_TRUNCATE_LENGTH = 50


# UI Configuration
RECENT_CONVERSATIONS_LIMIT = 5
MESSAGE_PREVIEW_LENGTH = 100


# Response Messages
ERROR_MESSAGES = {
    "EMPTY_MESSAGE": "Message cannot be empty",
    "MESSAGE_TOO_LONG": f"Message is too long (max {MAX_MESSAGE_LENGTH} characters)",
    "OLLAMA_CONNECTION": "QueryMind could not reach the answer service.",
    "OLLAMA_ERROR": "QueryMind could not finish this answer. Try again in a moment.",
    "NO_RESPONSE": "QueryMind did not receive an answer. It will not invent results.",
    "INVALID_JSON": "Invalid JSON in request",
}


# Product display names (not the underlying model)
AI_DISPLAY_NAME = "QueryMind"
AI_AVATAR_TEXT = "QM"

EXAMPLE_QUESTIONS = [
    "How many products do we currently sell?",
    "Which products are out of stock?",
    "What are our latest orders?",
    "How much revenue came from paid orders?",
]


# for gemini
GEMINI_API_KEY = ""
