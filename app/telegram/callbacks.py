from __future__ import annotations

from datetime import datetime, timezone, time, timedelta
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


def _parse_hhmm(value: Any) -> Optional[time]:
    """Parse a simple 'HH:MM' string into a time object.

    This expects already-normalized values coming from the GPT fallback.
    If parsing fails, we return None and let the existing value pass through.
    """
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
    """Normalize sleep_start / sleep_end into proper timestamptz values.

    Input values are expected to be 'HH:MM' strings (or left untouched if
    GPT normalization was skipped). We anchor the window to *today* for
    sleep_end. If both times exist and start > end we assume the sleep
    started yesterday (cross-midnight window) – Option B in the spec.
    """
    start_raw = record.get("sleep_start")
    end_raw = record.get("sleep_end")

    if not start_raw and not end_raw:
        return record

    today = datetime.now(timezone.utc).date()

    start_time = _parse_hhmm(start_raw)
    end_time = _parse_hhmm(end_raw)

    if start_time is None and end_time is None:
        # Nothing we can safely normalize
        return record

    end_dt = None
    if end_time is not None:
        end_dt = datetime.combine(today, end_time, tzinfo=timezone.utc)

    start_date = today
    if start_time is not None and end_time is not None and start_time > end_time:
        # Cross-midnight sleep: start is yesterday
        start_date = today - timedelta(days=1)

    start_dt = None
    if start_time is not None:
        start_dt = datetime.combine(start_date, start_time, tzinfo=timezone.utc)

    if start_dt is not None:
        record["sleep_start"] = start_dt
    if end_dt is not None:
        record["sleep_end"] = end_dt

    return record


def handle_callback(callback: Dict[str, Any]) -> None:
    """Central router for all inline button callback queries."""
    callback_id = callback.get("id")
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    data = callback.get("data", "")

    if not callback_id or not chat_id:
        return

    # 1) Main menu button
    if data == "main_menu":
        text, reply_markup = build_main_menu()
        send_message(chat_id, text, reply_markup=reply_markup)
        answer_callback_query(callback_id)
        return

    # 2) Start flows from menu / guidance buttons
    if data in {"log_food", "start_food"}:
        reply_text, reply_markup, new_state = start_food_flow(chat_id)
        set_state(chat_id, new_state)
        send_message(chat_id, reply_text, reply_markup=reply_markup)
        answer_callback_query(callback_id)
        return

    if data in {"log_sleep", "start_sleep"}:
        reply_text, reply_markup, new_state = start_sleep_flow(chat_id)
        set_state(chat_id, new_state)
        send_message(chat_id, reply_text, reply_markup=reply_markup)
        answer_callback_query(callback_id)
        return

    if data in {"log_exercise", "start_exercise"}:
        reply_text, reply_markup, new_state = start_exercise_flow(chat_id)
        set_state(chat_id, new_state)
        send_message(chat_id, reply_text, reply_markup=reply_markup)
        answer_callback_query(callback_id)
        return

    # Fetch state once – flows below rely on it.
    state = get_state(chat_id)

    # 3) Food flow callbacks
    if (state and state.get("flow") == "food") or data.startswith("food_"):
        reply_text, reply_markup, new_state = handle_food_callback(chat_id, data, state)

        if state and state.get("step") == "preview" and data == "food_confirm":
            final_state = new_state or state
            food_data = final_state.get("data") or {}
            record = dict(food_data)
            record["chat_id"] = str(chat_id)
            record["date"] = datetime.now(timezone.utc).date().isoformat()

            success, error = insert_record("food", record)
            if not success:
                send_message(chat_id, f"❌ Could not log your meal.\n{error}")
                clear_state(chat_id)
                answer_callback_query(callback_id)
                return

            clear_state(chat_id)
            send_message(chat_id, "✅ Meal logged successfully.")
            answer_callback_query(callback_id)
            return

        if new_state is None:
            clear_state(chat_id)
        else:
            set_state(chat_id, new_state)

        send_message(chat_id, reply_text, reply_markup=reply_markup)
        answer_callback_query(callback_id)
        return

    # 4) Sleep flow callbacks
    if (state and state.get("flow") == "sleep") or data.startswith("sleep_"):
        reply_text, reply_markup, new_state = handle_sleep_callback(chat_id, data, state)

        if state and state.get("step") == "preview" and data == "sleep_confirm":
            final_state = new_state or state
            sleep_data = final_state.get("data") or {}
            record = dict(sleep_data)
            record["chat_id"] = str(chat_id)
            record["date"] = datetime.now(timezone.utc).date().isoformat()

            # Normalize sleep_start / sleep_end into proper timestamptz values
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

        if new_state is None:
            clear_state(chat_id)
        else:
            set_state(chat_id, new_state)

        send_message(chat_id, reply_text, reply_markup=reply_markup)
        answer_callback_query(callback_id)
        return

    # 5) Exercise flow callbacks
    if (state and state.get("flow") == "exercise") or data.startswith("ex_"):
        reply_text, reply_markup, new_state = handle_exercise_callback(chat_id, data, state)

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

        if new_state is None:
            clear_state(chat_id)
        else:
            set_state(chat_id, new_state)

        send_message(chat_id, reply_text, reply_markup=reply_markup)
        answer_callback_query(callback_id)
        return

    # 6) Fallback – just close the spinner
    answer_callback_query(callback_id)
