"""LLM models + pricing knobs (prompts live in backend.llm.prompts)."""

from __future__ import annotations

DEFAULT_MODEL_DEMO = "claude-sonnet-4-5-20250929"
DEFAULT_MODEL_EVAL = "claude-haiku-4-5-20251001"

# Rough Anthropic pricing USD / 1M tokens (cost estimates only)
PRICE_PER_MTOK: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"in": 1.0, "out": 5.0},
    "claude-sonnet-4-5-20250929": {"in": 3.0, "out": 15.0},
    "default": {"in": 3.0, "out": 15.0},
}
