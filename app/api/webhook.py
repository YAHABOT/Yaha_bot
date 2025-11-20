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
from app.telegram.state import get_state, set_state, clear_state
from app.telegram.flows.food_flow import (
    start_food_flow,
    handle_food_callback,
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
    if "callback_query" in update:
        _handle_callback_query(update["callback_query"])
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


def _handle_callback_query(callback: Dict[str, Any]) -> None:
    """
    Handle inline keyboard presses:
    - Food flow callbacks
    - Generic 'start_*' callbacks (guidance)
    """
    callback_id = callback.get("id")
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    data = callback.get("data", "")

    if not callback_id or not chat_id:
        return

    # 1) If food flow is active OR this callback starts it, handle via food flow
    state = get_state(chat_id)

    # Start food flow explicitly from inline button (e.g. from unknown message guidance)
    if data in ("start_food", "food_start"):
        reply_text, reply_markup, new_state = start_food_flow(chat_id)
        set_state(chat_id, new_state)
        send_message(chat_id, reply_text, reply_markup=reply_markup)
        answer_callback_query(callback_id)
        return

    # If we are already in a food flow, route callback there
    if state and state.get("flow") == "food" and data.startswith("food_"):
        reply_text, reply_markup, new_state = handle_food_callback(chat_id, data, state)

        # Special case: confirmation step triggers DB write
        if state.get("step") == "preview" and data == "food_confirm":
            # We expect new_state to still contain the final data
            final_state = new_state or state
            food_data = final_state.get("data") or {}

            # Prepare final record for Supabase
            record = dict(food_data)
            record["chat_id"] = str(chat_id)
            record["date"] = _today_utc_iso()

            success, error = insert_record("food", record)
            if not success:
                logging.error("[SUPABASE ERROR food] %s", error)
                send_message(chat_id, f"❌ Could not log your meal.\n{error}")
                log_entry(
                    chat_id=str(chat_id),
                    raw_text=food_data.get("meal_name") or "",
                    parsed=food_data,
                    container="food",
                    error=str(error),
                )
                clear_state(chat_id)
                answer_callback_query(callback_id)
                return

            # Successful write: clear state and confirm
            clear_state(chat_id)
            send_message(chat_id, "✅ Meal logged successfully.")
            answer_callback_query(callback_id)
            return

        # Regular branch (non-confirm)
        if new_state is None:
            clear_state(chat_id)
        else:
            set_state(chat_id, new_state)

        send_message(chat_id, reply_text, reply_markup=reply_markup)
        answer_callback_query(callback_id)
        return

    # 2) Fallback: generic UX callbacks (legacy guidance)
    reply = build_callback_reply(data)
    if reply is None:
        answer_callback_query(callback_id)
        return

    text, reply_markup = reply
    send_message(chat_id, text, reply_markup=reply_markup)
    answer_callback_query(callback_id)
