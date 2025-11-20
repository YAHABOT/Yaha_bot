# app/telegram/state.py
from __future__ import annotations

from typing import Any, Dict, Optional

# Simple in-memory state store: chat_id -> state dict
# This is fine for MVP on a single Render instance.
_STATE: Dict[str, Dict[str, Any]] = {}


def get_state(chat_id: int | str) -> Optional[Dict[str, Any]]:
    """
    Return the current conversation state for this chat_id,
    or None if no active flow.
    """
    key = str(chat_id)
    return _STATE.get(key)


def set_state(chat_id: int | str, state: Dict[str, Any]) -> None:
    """
    Set or update the conversation state for this chat_id.
    """
    key = str(chat_id)
    _STATE[key] = state


def clear_state(chat_id: int | str) -> None:
    """
    Clear the conversation state for this chat_id.
    """
    key = str(chat_id)
    _STATE.pop(key, None)
