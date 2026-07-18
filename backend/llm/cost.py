"""Token cost estimates (rough Anthropic list prices)."""

from __future__ import annotations

from backend.settings.constants.llm import PRICE_PER_MTOK


def estimate_cost(model: str, in_tok: int, out_tok: int) -> float:
    prices = PRICE_PER_MTOK.get(model, PRICE_PER_MTOK["default"])
    return (in_tok * prices["in"] + out_tok * prices["out"]) / 1_000_000
