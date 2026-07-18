"""LLM layer — client, prompts, parse, cost (provider-facing)."""

from backend.llm.client import complete, get_client
from backend.llm.cost import estimate_cost
from backend.llm.parse import parse_json_loose
from backend.llm.prompts import (
    CHAT_SYSTEM_PROMPT,
    EXTRACT_SYSTEM_PROMPT,
    EXTRACT_USER_TEMPLATE,
    JSON_REPAIR_USER,
)

__all__ = [
    "CHAT_SYSTEM_PROMPT",
    "EXTRACT_SYSTEM_PROMPT",
    "EXTRACT_USER_TEMPLATE",
    "JSON_REPAIR_USER",
    "complete",
    "estimate_cost",
    "get_client",
    "parse_json_loose",
]
