"""Constants and configuration for the chat application"""

# Ollama API Configuration
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_CHAT_ENDPOINT = f"{OLLAMA_BASE_URL}/api/chat"
OLLAMA_MODEL = "qwen2.5:3b"
OLLAMA_TIMEOUT = 100.0  # seconds
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
    "OLLAMA_CONNECTION": "Could not connect to the local Qwen model",
    "OLLAMA_ERROR": "Sorry, I'm having trouble connecting to Qwen 2.5 3B.",
    "NO_RESPONSE": "No response received from the model",
    "INVALID_JSON": "Invalid JSON in request",
}


# Model Display Names
AI_DISPLAY_NAME = "Qwen 2.5 3B"
AI_AVATAR_TEXT = "Q2.5"


# for gemini
GEMINI_API_KEY = ""
