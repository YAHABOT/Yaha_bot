from __future__ import annotations

from datetime import datetime, timezone, timedelta, time
from typing import Any, Dict, Optional

from app.services.supabase import insert_record
from app.services.telegram import answer_callback_query, send_message
from app.telegram.flows.exercise_flow import (
    handle_exercise_callback,
    start_exercise_flow,
)
from app.telegram.flows.food_flow import (
    handle_food_callback,
    start_food_flow,
)
from app.telegram.flows.sleep_flow import (
    handle_sleep_callback,
    start_sleep_flow,
)
from app.telegram.state import clear_state, get_state, set_state
from app.telegram.ux import build_main_menu


# -----------------------------
# TIME HELPERS
# -----------------------------

def _parse_hhmm(value: Any) -> Optional[time]:
    """Parse 'HH:MM' or 'HH.MM' into a time object."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None

    for fmt in ("%H:%M", "%H.%M"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue

    return None


def _attach_sleep_timestamps(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert sleep_start/sleep_end "HH:MM" strings into ISO8601 timestamps.
    Implements Option B:
       If start_time > end_time → sleep_start = yesterday, sleep_end = today
    Ensures values are JSON serializable ISO strings so Supabase accepts them.
    """
    start_raw = record.get("sleep_start")
    end_raw = record.get("sleep_end")

    if not start_raw and not end_raw:
        return record

    today = datetime.now(timezone.utc).date()

    start_time = _parse_hhmm(start_raw)
    end_time = _parse_hhmm(end_raw)

    # If both fail parsing, leave as-is
    if start_time is None and end_time is None:
        return record

    # Determine correct date offsets
    start_date = today
    if start_time and end_time and start_time > end_time:
        # Cross-midnight window: start was yesterday
        start_date = today - timedelta(days=1)

    start_dt = datetime.combine(start_date, start_time, tzinfo=timezone.utc) if start_time else None
    end_dt = datetime.combine(today, end_time, tzinfo=timezone.utc) if end_time else None

    # Convert to JSON-safe ISO strings
    if start_dt:
        record["sleep_start"] = start_dt.isoformat()
    if end_dt:
        record["sleep_end"] = end_dt.isoformat()

    return record


# -----------------------------
# CALLBACK ROUTER
# -----------------------------

def handle_callback(callback: Dict[str, Any]) -> None:
    """
    Central router for all callback queries.
    This must match the calling signature used in webhook.py.
    """
    callback_id = callback.get("id")
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    data = callback.get("data", "")

    if not callback_id or not chat_id:
        return

    #
    # MAIN MENU
    #
    if data == "main_menu":
        text, reply_markup = build_main_menu()
        send_message(chat_id, text, reply_markup=reply_markup)
        answer_callback_query(callback_id)
        return

    #
    # FLOW ENTRY POINTS
    #
    if data in {"log_sleep", "start_sleep"}:
        reply_text, reply_markup, new_state = start_sleep_flow(chat_id)
        set_state(chat_id,
