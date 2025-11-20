from __future__ import annotations

import os
from typing import Dict


def load_parser_pack() -> Dict[str, str]:
    """
    Return metadata for the Parser Pack v2 used by the classifier.

    For now, we simply wrap the GPT_PROMPT_ID from environment
    and fix version="1" to align with how your current backend
    calls the Responses API.
    """
    prompt_id = os.getenv("GPT_PROMPT_ID", "")

    if not prompt_id:
        # We do NOT crash here – the caller should handle missing IDs.
        # This keeps behaviour safe in non-configured environments.
        return {
            "id": "",
            "version": "1",
        }

    return {
        "id": prompt_id,
        "version": "1",
    }
