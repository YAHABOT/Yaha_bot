# app/api/webhook.py
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from flask import Blueprint, jsonify, request

from app.parser_engine.router import parse_text_message
from app.services.telegram import send_message, answer_callback_query
from app.services.supabase import insert_record, log_entry
from app.telegram import build_reply_for_parsed, build_callback_reply

api = Blueprint("api", __name__)

VALID_CONTAINERS = {"food", "sleep", "exercise"}


def _today_utc_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


@api.route("/", methods=["GET"])
def healthcheck() -> str:
    return "YAHA bot running"


@api.route("/webhook", methods=["POST"])
def webhook() -> Any:
    update: Dict[str, Any] = request.get_json(silent=True) or {}

    # --- CALLBACK QUERIES (inline buttons) ----------------------------------
    if "callback_query" in update:
        _handle_callback_query(update["callback_query"])
        return jsonify({"ok": True})

    # --- TEXT MESSAGES ------------------------------------------------------
    message = update.get("message")
    if not message or "text" not in message:
        # Ignore non-text updates for now (photos/voice will come later modules)
        return jsonify({"ok": True})

    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    raw_text = message.get("text", "").strip()

    if not chat_id or not raw_text:
        return jsonify({"ok": True})

    # Parse via GPT parser engine
    try:
        parsed = parse_text_message(raw_text)
    except Exception as e:  # hard fail from parser
        logging.exception("[PARSER ERROR] %s", e)
        send_message(chat_id, "❌ I hit an internal error while parsing that. Try again.")
        # Log into entries as a hard error
        log_entry(
            chat_id=str(chat_id),
            raw_text=raw_text,
            parsed={},
            container="error",
            error=str(e),
        )
        return jsonify({"ok": False})

    container = parsed.get("container", "unknown")
    data = parsed.get("data") or {}

    # Build UX reply (pretty message + optional keyboard)
    reply_text, reply_markup = build_reply_for_parsed(raw_text, parsed)

    # Unknown / invalid containers → do NOT write to domain tables
    if container not in VALID_CONTAINERS:
        log_entry(
            chat_id=str(chat_id),
            raw_text=raw_text,
            parsed=parsed,
            container=container,
            error="invalid_or_unknown_container",
        )
        send_message(chat_id, reply_text, reply_markup=reply_markup)
        return jsonify({"ok": True})

    # Valid container → write to Supabase table
    final_data = dict(data)
    final_data["chat_id"] = str(chat_id)
    final_data["date"] = _today_utc_iso()

    success, error = insert_record(container, final_data)

    if not success:
        logging.error("[SUPABASE ERROR %s] %s", container, error)
        send_message(chat_id, f"❌ Could not log entry.\n{error}")
        log_entry(
            chat_id=str(chat_id),
            raw_text=raw_text,
            parsed=parsed,
            container=container,
            error=str(error),
        )
        return jsonify({"ok": False})

    # Successful write
    send_message(chat_id, reply_text, reply_markup=reply_markup)
    return jsonify({"ok": True})


def _handle_callback_query(callback: Dict[str, Any]) -> None:
    """
    Handle inline keyboard presses for 'Log food / sleep / exercise'.
    """
    callback_id = callback.get("id")
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    data = callback.get("data", "")

    if not callback_id or not chat_id:
        return

    reply = build_callback_reply(data)
    if reply is None:
        # Graceful no-op
        answer_callback_query(callback_id)
        return

    text, reply_markup = reply
    send_message(chat_id, text, reply_markup=reply_markup)
    answer_callback_query(callback_id)
