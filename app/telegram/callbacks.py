# app/telegram/callbacks.py
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from app.services.telegram import answer_callback_query, send_message
from app.telegram.state import get_state, set_state, clear_state
from app.telegram.ux import build_main_menu
from app.telegram.flows.food_flow import (
    start_food_flow,
    handle_food_callback,
)
from app.telegram.flows.sleep_flow import start_sleep_flow
from app.telegram.flows.exercise_flow import start_exercise_flow

# For this file, I'll implement the router.

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

    # 6. Existing Food Flow Callbacks
    # If we are in food flow or data starts with food_
    state = get_state(chat_id)
    if (state and state.get("flow") == "food") or data.startswith("food_"):
        # Delegate to food flow handler (logic moved from webhook.py or imported)
        # Note: webhook.py had special logic for 'food_confirm' writing to DB.
        # We need to preserve that or move it here.
        # The Task Pack says "Route them to callbacks.py".
        # It seems safer to import the handler from food_flow, BUT
        # food_flow.handle_food_callback returns (text, markup, new_state).
        # It does NOT write to DB. The DB write was in webhook.py.
        # I should probably move that DB write logic here to keep webhook.py clean.
        
        # Let's handle the delegation carefully.
        reply_text, reply_markup, new_state = handle_food_callback(chat_id, data, state)
        
        # Check for completion (this logic was in webhook.py)
        if state and state.get("step") == "preview" and data == "food_confirm":
             # This is where the DB write happened in webhook.py.
             # I will need to import insert_record etc.
             # To avoid circular imports or massive code duplication right now,
             # I will implement the DB write here as it was in webhook.py.
             from app.services.supabase import insert_record, log_entry
             from datetime import datetime, timezone
             
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

    # 7. Fallback / Unknown
    answer_callback_query(callback_id)
