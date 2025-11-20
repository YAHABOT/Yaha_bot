# app/services/telegram.py
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def _post(endpoint: str, payload: Dict[str, Any]) -> None:
    url = f"{TELEGRAM_API_BASE}/{endpoint}"
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception:
        # We deliberately swallow Telegram errors here; logging is done upstream
        pass


def send_message(
    chat_id: int | str,
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Send a message to a Telegram chat.

    reply_markup can be an inline keyboard dict, e.g.:
    {
        "inline_keyboard": [[{"text": "Button", "callback_data": "foo"}]]
    }
    """
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    _post("sendMessage", payload)


def answer_callback_query(
    callback_query_id: str,
    text: Optional[str] = None,
    show_alert: bool = False,
) -> None:
    """
    Acknowledge a callback query so Telegram stops the 'loading' spinner.
    """
    payload: Dict[str, Any] = {
        "callback_query_id": callback_query_id,
        "show_alert": bool(show_alert),
    }
    if text:
        payload["text"] = text

    _post("answerCallbackQuery", payload)
