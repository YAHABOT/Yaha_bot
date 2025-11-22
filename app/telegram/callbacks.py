# app/telegram/callbacks.py
from __future__ import annotations

from typing import Any, Dict
from datetime import datetime, timezone

from app.services.telegram import answer_callback_query, send_message
from app.services.supabase import insert_record, log_entry
from app.telegram.state import get_state, set_state, clear_state
from app.telegram.ux import build_main_menu
from app.telegram.flows.food_flow import (
    start_food_flow,
    handle_food_callback,
)
from app.telegram.flows.sleep_flow import (
    start_sleep_flow,
    handle_sleep_callback,
)
from app.telegram.flows.exercise_flow import (
    start_exercise_flow,
    handle_exercise_callback,
)


def handle_callback(callback: Dict[str, Any]) -> None:
    """
    Central router for all callback queries.
    """
    callback_id = callback.get("id")
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    data = callback.get("data", "")

    if not callback_id or not chat_id:
        return

    # 1. Main Menu
    if data == "main_menu":
        text, reply_markup = build_main_menu()
        send_message(chat_id, text, reply_markup=reply_markup)
        answer_callback_query(callback_id)
        return

    # 2. Log Food (Start Flow)
    if data == "log_food" or data == "start_food":
        reply_text, reply_markup, new_state = start_food_flow(chat_id)
        set_state(chat_id, new_state)
        send_message(chat_id, reply_text, reply_markup=reply_markup)
        answer_callback_query(callback_id)
        return

    # 3. Log Sleep (Start Flow)
    if data == "log_sleep" or data == "start_sleep":
        reply_text, reply_markup, new_state = start_sleep_flow(chat_id)
        set_state(chat_id, new_state)
        send_message(chat_id, reply_text, reply_markup=reply_markup)
        answer_callback_query(callback_id)
        return

    # 4. Log Exercise (Start Flow)
    if data == "log_exercise" or data == "start_exercise":
        reply_text, reply_markup, new_state = start_exercise_flow(chat_id)
        set_state(chat_id, new_state)
        send_message(chat_id, reply_text, reply_markup=reply_markup)
        answer_callback_query(callback_id)
        return

    # 5. View Day
    if data == "view_day":
        send_message(chat_id, "📋 Daily summary coming soon!")
        answer_callback_query(callback_id)
        return

    # Fetch current state (for all flows)
    state = get_state(chat_id)

    # 6. Food Flow Callbacks
    if (state and state.get("flow") == "food") or data.startswith("food_"):
        reply_text, reply_markup, new_state = handle_food_callback(chat_id, data, state)

        # Completion: confirm food log
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

    # 7. Sleep Flow Callbacks
    if (state and state.get("flow") == "sleep") or data.startswith("sleep_"):
        reply_text, reply_markup, new_state = handle_sleep_callback(chat_id, data, state)

        # Completion: confirm sleep log
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

    # 8. Exercise Flow Callbacks
    if (state and state.get("flow") == "exercise") or data.startswith("ex_"):
        reply_text, reply_markup, new_state = handle_exercise_callback(chat_id, data, state)

        # Completion: confirm exercise log
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

    # 9. Fallback / Unknown
    answer_callback_query(callback_id)