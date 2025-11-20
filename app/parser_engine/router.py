from __future__ import annotations

from typing import Dict, Any

from .classifier import classify_message
from .validator import validate_container


def parse_text_message(text: str) -> Dict[str, Any]:
    """
    High-level entrypoint for TEXT messages.

    Pipeline:
    1. Classify using rule-based + GPT Parser Pack v2.
    2. Validate the 'data' payload against the container schema.
    3. Attach any schema errors to 'issues'.
    4. Return a plain dict matching the Parser Contract v2.
    """
    output = classify_message(text)  # ParserOutput

    # Schema validation
    is_valid, err = validate_container(output.container, output.data)
    if not is_valid and err:
        output.issues.append(f"Schema validation failed: {err}")

    # Return JSON-contract dict
    return output.to_dict()
