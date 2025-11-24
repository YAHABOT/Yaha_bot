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


# --------------------------------------------------------
# TIME HELPERS
# --------------------------------------------------------

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
    Convert sleep_start/sleep_end 'HH:MM' into ISO8601 strings.

    Implements Option B:
    - If start_time > end_time → sleep_start = yesterday
    - Ensures Supabase receives JSON-safe ISO8601 strings
    """
    start_raw = record.get("sleep_start")
    end_raw = record.get("sleep_end")

    if not start_raw and not end_raw:
        return record

    today = datetime.now(timezone.utc).date()

    start_time = _parse_hhmm(start_raw)
    end_time = _parse_hhmm(end_raw)

    # If both failed parsing → leave unchanged
    if start_time is None and end_time is None:
        return record

    # Determine correct date (cross midnight logic)
    start_date = today
    if start_time and end_time and start_time > end_time:
        start_date = today - timedelta(days=1)

    start_dt = None
    end_dt = None

    if start_time:
        start_dt = datetime.combine(start_date, start_time, tzinfo=timezone.utc)

    if end_time:
        end_dt = datetime.combine(today, end_time, tzinfo=timezone.utc)

    # Convert both into JSON-safe strings
    if start_dt:
        record["sleep_start"] = start_dt.isoformat()

    if end_dt:
        record["sleep_end"] = end_dt.isoformat()

    return record


# --------------------------------------------------------
# CALLBACK ROUTER
# --------------------------------------------------------

def handle_callback(callback: Dict[str, Any]) -> None:
    """
    Central router for all callback queries.
    MUST match signature used by webhook.py.
    """
    callback_id = callback.get("id")
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    data = callback.get("data", "")

    if not callback_id or not chat_id:
        return

    # -----------------------
    # MAIN MENU
    # -----------------------
    if data == "main_menu":
        text, reply_markup = build_main_menu()
        send_message(chat_id, text, reply_markup=reply_markup)
        answer_callback_query(callback_id)
        return

    # -----------------------
    # FLOW ENTRY BUTTONS
    # -----------------------
    if data in {"log_sleep", "start_sleep"}:
        text, markup, new_state = start_sleep_flow(chat_id)
        set_state(chat_id, new_state)
        send_message(chat_id, text, reply_markup=markup)
        answer_callback_query(callback_id)
        return

    if data in {"log_food", "start_food"}:
        text, markup, new_state = start_food_flow(chat_id)
        set_state(chat_id, new_state)
        send_message(chat_id, text, reply_markup=markup)
        answer_callback_query(callback_id)
        return

    if data in {"log_exercise", "start_exercise"}:
        text, markup, new_state = start_exercise_flow(chat_id)
        set_state(chat_id, new_state)
        send_message(chat_id, text, reply_markup=markup)
        answer_callback_query(callback_id)
        return

    # -----------------------
    # LOAD STATE
    # -----------------------
    state = get_state(chat_id)

    # --------------------------------------------------------
    # SLEEP FLOW
    # --------------------------------------------------------
    if (state and state.get("flow") == "sleep") or data.startswith("sleep_"):
        reply_text, reply_markup, new_state = handle_sleep_callback(chat_id, data, state)

        # Final confirmation
        if state and state.get("step") == "preview" and data == "sleep_confirm":
            final_state = new_state or state
            sleep_data = final_state.get("data") or {}

            record = dict(sleep_data)
            record["chat_id"] = str(chat_id)
            record["date"] = datetime.now(timezone.utc).date().isoformat()

            # Full timestamp fix
            record = _attach_sleep_timestamps(record)

            success, error = insert_record("sleep", record)
            if not success:
                send_message(chat_id, f"❌ Could not log sleep.\n{error}")
                clear_state(chat_id)
                answer_callback_query(callback_id)
                return

            clear_state(chat_id)
            send_message(chat_id, "✅ Sleep logged successfully.")
            answer_callback_query(callback_id)
            return

        # Continue flow
        if new_state is None:
            clear_state(chat_id)
        else:
            set_state(chat_id, new_state)

        send_message(chat_id, reply_text, reply_markup=reply_markup)
        answer_callback_query(callback_id)
        return

    # --------------------------------------------------------
    # FOOD FLOW
    # --------------------------------------------------------
    if (state and state.get("flow") == "food") or data.startswith("food_"):
        reply_text, reply_markup, new_state = handle_food_callback(chat_id, data, state)

        # Confirmation
        if state and state.get("step") == "preview" and data == "food_confirm":
            final_state = new_state or state
            food_data = final_state.get("data") or {}

            record = dict(food_data)
            record["chat_id"] = str(chat_id)
            record["date"] = datetime.now(timezone.utc).date().isoformat()

            success, error = insert_record("food", record)
            if not success:
                send_message(chat_id, f"❌ Could not log food.\n{error}")
                clear_state(chat_id)
                answer_callback_query(callback_id)
                return

            clear_state(chat_id)
            send_message(chat_id, "✅ Food logged successfully.")
            answer_callback_query(callback_id)
            return

        # Continue food flow
        if new_state is None:
            clear_state(chat_id)
        else:
            set_state(chat_id, new_state)

        send_message(chat_id, reply_text, reply_markup=reply_markup)
        answer_callback_query(callback_id)
        return

    # --------------------------------------------------------
    # EXERCISE FLOW
    # --------------------------------------------------------
    if (state and state.get("flow") == "exercise") or data.startswith("ex_"):
        reply_text, reply_markup, new_state = handle_exercise_callback(chat_id, data, state)

        # Confirmation
        if state and state.get("step") == "preview" and data == "ex_confirm":
            final_state = new_state or state
            ex_data = final_state.get("data") or {}

            record = dict(ex_data)
            record["chat_id"] = str(chat_id)
            record["date"] = datetime.now(timezone.utc).date().isoformat()

            success, error = insert_record("exercise", record)
            if not success:
                send_message(chat_id, f"❌ Could not log workout.\n{error}")
                clear_state(chat_id)
                answer_callback_query(callback_id)
                return

            clear_state(chat_id)
            send_message(chat_id, "✅ Workout logged successfully.")
            answer_callback_query(callback_id)
            return

        # Continue exercise flow
        if new_state is None:
            clear_state(chat_id)
        else:
            set_state(chat_id, new_state)

        send_message(chat_id, reply_text, reply_markup=reply_markup)
        answer_callback_query(callback_id)
        return

    # --------------------------------------------------------
    # FALLBACK
    # --------------------------------------------------------
    answer_callback_query(callback_id)
