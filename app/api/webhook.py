# app/api/webhook.py
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from flask import Blueprint, jsonify, request

from app.parser_engine.router import parse_text_message
from app.services.telegram import send_message
from app.services.supabase import insert_record, log_entry
from app.telegram import build_reply_for_parsed
from app.telegram.state import get_state, set_state, clear_state
from app.telegram.callbacks import handle_callback
from app.telegram.ux import build_main_menu
from app.telegram.flows.food_flow import (
    start_food_flow,
    handle_food_text,
)

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
    # --- CALLBACK QUERIES (inline buttons) ----------------------------------
    if "callback_query" in update:
        handle_callback(update["callback_query"])
        return jsonify({"ok": True})

    # --- TEXT MESSAGES ------------------------------------------------------
    message = update.get("message")
    if not message or "text" not in message:
        # For now, ignore non-text updates in this step
        return jsonify({"ok": True})

    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    raw_text = message.get("text", "").strip()

    if not chat_id or not raw_text:
        return jsonify({"ok": True})

    # Check if this chat is in a multi-step flow
    state = get_state(chat_id)
    if state and state.get("flow") == "food":
        # Route text into food flow handler, no GPT usage
        reply_text, reply_markup, new_state = handle_food_text(chat_id, raw_text, state)

        if new_state is None:
            clear_state(chat_id)
        else:
            set_state(chat_id, new_state)

        send_message(chat_id, reply_text, reply_markup=reply_markup)
        return jsonify({"ok": True})

    # No active flow: commands / shortcuts first
    lower = raw_text.lower()
    if lower == "menu":
        text, reply_markup = build_main_menu()
        send_message(chat_id, text, reply_markup=reply_markup)
        return jsonify({"ok": True})

    if lower in ("/food", "log food", "add food", "log meal"):
        reply_text, reply_markup, new_state = start_food_flow(chat_id)
        set_state(chat_id, new_state)
        send_message(chat_id, reply_text, reply_markup=reply_markup)
        return jsonify({"ok": True})

    # Otherwise, default to Parser Engine v2 (GPT + schemas)
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



