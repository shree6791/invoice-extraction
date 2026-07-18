"""LLM escalation cascade — difficulty classifier + routing.

Production cascade (docs/EXTRACTION.md):
    Stage 2a: LayoutLMv3 / self-hosted 7B  → fast, cheap, known templates
    Stage 2b: Fine-tuned 70B               → complex cases
    Stage 2c: Claude                        → edge cases, new templates

This file mocks stages 2a + 2c:
    easy → MockFastExtractor (regex, < 5 ms, simulates 1 s GPU)
             └─ needs_review non-empty → escalate to Claude
    hard → Claude directly (no fast-model attempt)

Routing decisions are surfaced in ExtractResult.routing so every API response
shows which path was taken — observable behaviour, not a black box.
"""

from __future__ import annotations

from typing import Literal

from backend.models.layout import ParsedDocument

Difficulty = Literal["easy", "hard"]


def classify_difficulty(parsed: ParsedDocument) -> Difficulty:
    """Heuristic difficulty classification.

    hard triggers:
      - Multi-page document (table continuation across pages)
      - Markdown too short to contain a real invoice (< 120 chars)
      - No markdown table found (no line-item structure to parse)

    Production replacement:
        A lightweight MLP classifier trained on layout features:
        [n_pages, n_tables, n_line_items, text_density, has_tax_line, ...]
        Returns a confidence score; below threshold → hard.
    """
    md = parsed.markdown or ""

    if len(parsed.pages) > 1:
        return "hard"

    if len(md.strip()) < 120:
        return "hard"

    if "|" not in md:
        return "hard"   # no markdown table → likely unstructured / scanned

    return "easy"
