from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from openai import OpenAI

# Lazily-initialized OpenAI client
_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    """
    Lazily initialize the OpenAI client so that importing this module
    does not explode if the key is missing (e.g. during local tests).
    """
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logging.error("OPENAI_API_KEY is not set; GPT fallback is unavailable.")
            raise RuntimeError("OPENAI_API_KEY is not set")
        _client = OpenAI(api_key=api_key)
    return _client


SYSTEM_PROMPT = """
You are a data normalization engine for a health tracking bot.
Your only job is to extract structured fields from messy natural language.

You MUST respond with pure JSON only. No markdown, no prose.

Supported contexts and expected JSON shapes:

1) "number"
   - Extract a single numeric value from the text.
   - Return: { "number": <int_or_float_or_null> }

2) "duration"
   - Sleep: hours (possibly decimal).
   - Exercise: minutes (integer or decimal).
   - Understand phrases like "around 6 hours", "about 45 min", "1h15".
   - Return: { "duration": <float_or_null> }

3) "time"
   - A time of day in 24h "HH:MM" format.
   - Understand 6am, 11pm, midnight, 23:00, 6:00, 06:00, "around 7", etc.
   - If you can infer the hour but not minutes, assume :00.
   - Return: { "time": "HH:MM" or null }

4) "macros"
   - Extract calories and optionally macros.
   - Return:
     {
       "calories": <float_or_null>,
       "protein": <float_or_null>,
       "carbs": <float_or_null>,
       "fat": <float_or_null>,
       "fiber": <float_or_null>
     }

5) "exercise_stats"
   - Extract distance, calories, and heart rate where present.
   - Return:
     {
       "distance": <float_or_null>,   // km
       "calories": <int_or_float_or_null>,
       "heart_rate": <int_or_null>
     }

Rules:
- If input is ambiguous or data is missing, use null for that field.
- If the user says "skip", "no", "none" or similar, treat everything as null.
- Never invent extra fields beyond the expected JSON for the given context.
"""


def normalize_input(text: str, context: str, current_data: Optional[dict] = None) -> Optional[dict]:
    """
    Normalize user text into structured data using a small GPT model.

    Args:
        text: Raw user input.
        context: One of: "number", "duration", "time", "macros", "exercise_stats".
        current_data: Optional dict with already-known values (for future use).

    Returns:
        dict with normalized fields (see SYSTEM_PROMPT), or None on failure.
    """
    if not text or not text.strip():
        return None

    lowered = text.strip().lower()
    if lowered in {"skip", "no", "none", "pass"}:
        return None

    try:
        client = _get_client()
    except RuntimeError:
        # Key missing → just let caller fall back to regex.
        return None

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "input_text": text,
                            "target_context": context,
                            "existing_data": current_data or {},
                        }
                    ),
                },
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if not content:
            return None
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            return None
        return parsed
    except Exception as e:  # noqa: BLE001
        logging.error("[GPT FALLBACK ERROR] %s", e)
        return None
