"""Parse LLM text into JSON (tolerates fences / trailing noise)."""

from __future__ import annotations

import json
import re
from typing import Any


def parse_json_loose(text: str) -> dict[str, Any]:
    text = text.strip()
    if "```" in text:
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```.*", "", text, flags=re.S)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)
