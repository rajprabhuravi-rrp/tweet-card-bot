"""Integration seam for the LLM highlight-marking pipeline.

The actual regex cleanup + Gemini/Groq-with-fallback logic lives in
check_keys.py at the repo root (user-maintained) -- this module just wires
it into the rendering pipeline so every fetched tweet goes through it.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from check_keys import process


def annotate_highlights(text: str) -> str:
    """Returns text with URLs/trailing CTAs stripped and LLM-chosen emphasis
    spans wrapped in **double asterisks** (see check_keys.py's PROMPT).
    check_keys.process() already degrades to plain cleaned text if both
    LLM providers fail or return something that fails validation."""
    return process(text)
