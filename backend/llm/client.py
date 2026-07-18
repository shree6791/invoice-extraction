"""Anthropic client + chat completion helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass

import anthropic
import httpx

from backend.settings.config import ANTHROPIC_API_KEY


@dataclass
class Completion:
    text: str
    latency_s: float
    input_tokens: int
    output_tokens: int


def get_client() -> anthropic.Anthropic:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")
    return anthropic.Anthropic(
        api_key=ANTHROPIC_API_KEY,
        http_client=httpx.Client(trust_env=False, timeout=120.0),
    )


def complete(
    client: anthropic.Anthropic,
    *,
    model: str,
    system: str,
    messages: list[dict[str, str]],
    max_tokens: int = 8192,
) -> Completion:
    t0 = time.perf_counter()
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    )
    latency = time.perf_counter() - t0
    text_parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    return Completion(
        text="\n".join(text_parts),
        latency_s=latency,
        input_tokens=int(getattr(resp.usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(resp.usage, "output_tokens", 0) or 0),
    )
