from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from flask import Blueprint, jsonify, request

from app.parser_engine.router import parse_text_message
from app.services.supabase import insert_record, log_entry
from app.services.telegram import send_message
from app.telegram import build_reply_for_parsed
from app.telegram.callbacks import handle_callback
from app.telegram.flows.exercise_flow import handle_exercise_text, start_exercise_flow
from app.telegram.flows.food_flow import handle_food_text, start_food_flow
from app.telegram.flows.sleep_flow import handle_sleep_text, start_sleep_flow
from app.telegram.state import clear_state, get_state, set_state
from app.telegram.ux import build_main_menu

api = Blueprint("api", __name__)

VALID_CONTAINERS = {"food", "sleep", "exercise"}


def _today_utc_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


@api.route("/", methods=["GET"])
def healthcheck() -> str:
    return "YAHA bot running"


@api.route("/webhook", methods=["POST"])
def webhook() -> Any:
    """
    Main Telegram webhook endpoint.

    Handles:
    - callback_query (inline buttons) via callbacks.py
    - multi-step flows (food / sleep / exercise)
    - top-level commands (/food, /sleep, /exercise, menu)
    - free-text logs via Parser Engine v2
    """
    update: Dict[str, Any] = request.get_json(silent=True) or {}

    # 1) Inline button callbacks
    if "callback_query" in update:
        handle_callback(update["callback_query"])
        return jsonify({"ok": True})

    # 2) Text messages
    message = update.get("message")
    if not message or "text" not in message:
        # Ignore non-text updates for now
        return jsonify({"ok": True})

    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    raw_text = message.get("text", "").strip()

    if not chat_id or not raw_text:
        return jsonify({"ok": True})

    # 3) Check multi-step flow state first
    state = get_state(chat_id)
    if state:
        flow = state.get("flow")

        if flow == "food":
            reply_text, reply_markup, new_state = handle_food_text(chat_id, raw_text, state)
            if new_state is None:
                clear_state(chat_id)
            else:
                set_state(chat_id, new_state)
            send_message(chat_id, reply_text, reply_markup=reply_markup)
            return jsonify({"ok": True})

        if flow == "sleep":
            reply_text, reply_markup, new_state = handle_sleep_text(chat_id, raw_text, state)
            if new_state is None:
                clear_state(chat_id)
            else:
                set_state(chat_id, new_state)
            send_message(chat_id, reply_text, reply_markup=reply_markup)
            return jsonify({"ok": True})

        if flow == "exercise":
            reply_text, reply_markup, new_state = handle_exercise_text(chat_id, raw_text, state)
            if new_state is None:
                clear_state(chat_id)
            else:
                set_state(chat_id, new_state)
            send_message(chat_id, reply_text, reply_markup=reply_markup)
            return jsonify({"ok": True})

    # 4) No active flow: handle commands / shortcuts
    lower = raw_text.lower()
    if lower == "menu":
        text, reply_markup = build_main_menu()
        send_message(chat_id, text, reply_markup=reply_markup)
        return jsonify({"ok": True})

    if lower in {"/food", "log food", "add food", "log meal"}:
        reply_text, reply_markup, new_state = start_food_flow(chat_id)
        set_state(chat_id, new_state)
        send_message(chat_id, reply_text, reply_markup=reply_markup)
        return jsonify({"ok": True})

    if lower in {"/sleep", "log sleep", "add sleep"}:
        reply_text, reply_markup, new_state = start_sleep_flow(chat_id)
        set_state(chat_id, new_state)
        send_message(chat_id, reply_text, reply_markup=reply_markup)
        return jsonify({"ok": True})

    if lower in {"/exercise", "log exercise", "log workout", "add workout"}:
        reply_text, reply_markup, new_state = start_exercise_flow(chat_id)
        set_state(chat_id, new_state)
        send_message(chat_id, reply_text, reply_markup=reply_markup)
        return jsonify({"ok": True})

    # 5) Otherwise, default to Parser Engine v2
    try:
        parsed = parse_text_message(raw_text)
    except Exception as e:  # noqa: BLE001
        logging.exception("[PARSER ERROR] %s", e)
        send_message(chat_id, "❌ I hit an internal error while parsing that. Try again.")
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

    # 6) Build user-facing reply
    reply_text, reply_markup = build_reply_for_parsed(raw_text, parsed)

    # Invalid / unknown containers → log but don't write to domain tables
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

    # 7) Valid container → write to Supabase
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

    send_message(chat_id, reply_text, reply_markup=reply_markup)
    return jsonify({"ok": True})
