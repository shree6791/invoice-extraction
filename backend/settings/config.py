"""Paths and environment — no domain constants here."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from backend.settings.constants.llm import DEFAULT_MODEL_DEMO, DEFAULT_MODEL_EVAL

# backend/settings/config.py → project root is parents[2]
ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DOCILE_ROOT = ROOT / "data" / "docile"
TENANTS_DIR = ROOT / "data" / "tenants"
OUTPUTS_DIR = ROOT / "outputs"
STATIC_DIR = ROOT / "frontend" / "static"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL_DEMO = os.getenv("ANTHROPIC_MODEL_DEMO", DEFAULT_MODEL_DEMO)
MODEL_EVAL = os.getenv("ANTHROPIC_MODEL_EVAL", DEFAULT_MODEL_EVAL)
