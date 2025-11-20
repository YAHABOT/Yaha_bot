from __future__ import annotations

import re
from typing import Dict, Any

from openai import OpenAI
from .contract import ParserOutput
from .parser_pack_v2 import load_parser_pack


client = OpenAI()


# ---------------------------------------------------------------------------
# RULE-BASED CLASSIFICATION LAYER
# ---------------------------------------------------------------------------

FOOD_KEYWORDS = [
    "kcal", "calories", "protein", "carbs", "fat", "fiber",
    "breakfast", "lunch", "dinner", "ate", "meal", "wrap", "oats",
]

SLEEP_KEYWORDS = [
    "slept", "sleep", "hours", "bed", "wake", "woke", "energy score",
    "sleep score", "nap",
]

EXERCISE_KEYWORDS = [
    "run", "km", "pace", "workout", "gym", "training", "cardio",
    "strength", "calories burned", "hr", "avg hr", "max hr",
]


def rule_based_guess(text: str) -> str:
    """Fast, deterministic container detection using keywords."""
    lower = text.lower()

    if any(k in lower for k in FOOD_KEYWORDS):
        return "food"
    if any(k in lower for k in SLEEP_KEYWORDS):
        return "sleep"
    if any(k in lower for k in EXERCISE_KEYWORDS):
        return "exercise"

    return "unknown"


# ---------------------------------------------------------------------------
# GPT CLASSIFIER LAYER
# ---------------------------------------------------------------------------

def gpt_classify(text: str) -> Dict[str, Any]:
    """Send message to the Parser Pack v2."""
    pack = load_parser_pack()

    response = client.responses.create(
        model="gpt-4.1",
        prompt={"id": pack["id"], "version": pack["version"]},
        input=[{"role": "user", "content": text}],
        max_output_tokens=512,
    )

    raw = response.output[0].content[0].text

    import json
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Total fallback
        return {
            "container": "unknown",
            "data": {"raw_text": text},
            "confidence": 0.0,
            "issues": ["Invalid JSON from GPT"],
            "reply_text": "⚠️ I could not classify this.",
        }


# ---------------------------------------------------------------------------
# MAIN ENTRYPOINT
# ---------------------------------------------------------------------------

def classify_message(text: str) -> ParserOutput:
    """
    Full classification pipeline:
    1. Rule-based guess
    2. Send to GPT Parser Pack
    3. Shape into ParserOutput
    """
    if not text or not text.strip():
        return ParserOutput.unknown(
            raw_text=text,
            reason="Empty or blank message",
        )

    # 1) Rule-based initial guess
    guess = rule_based_guess(text)

    # 2) GPT parser pack
    gpt_raw = gpt_classify(text)

    # 3) Try to merge rule-based + GPT
    container = gpt_raw.get("container", guess) or guess
    data = gpt_raw.get("data", {})
    confidence = gpt_raw.get("confidence", 0.0)
    issues = gpt_raw.get("issues", [])
    reply_text = gpt_raw.get("reply_text",_
