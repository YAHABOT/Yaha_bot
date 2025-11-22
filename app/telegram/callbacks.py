from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

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


def handle_callback(callback: Dict[str, Any]) -> None:
    """
    Central router for all inline button callback queries.
    """
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
