import os
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from flask import Flask, request
from openai import OpenAI

# ----------------------------------------------------
# Flask app
# ----------------------------------------------------
app = Flask(__name__)

# ----------------------------------------------------
# Environment variables
# ----------------------------------------------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")  # e.g. https://xxx.supabase.co/rest/v1
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY")

# We are NOT using GPT_PROMPT_ID here to keep things simple and robust.
# All parser instructions live in this file for now.
openai_client = OpenAI(api_key=OPENAI_API_KEY)

LISBON_TZ = ZoneInfo("Europe/Lisbon")

# ----------------------------------------------------
# Logging setup
# ----------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# ----------------------------------------------------
# Parser system prompt
# ----------------------------------------------------
PARSER_SYSTEM_PROMPT = """
You are the YAHA ingestion parser.

Goal
-----
Given ONE Telegram message at a time, decide whether it is a log for FOOD, SLEEP, or EXERCISE,
and extract structured fields for Supabase.

You ALWAYS respond with a single JSON object. No prose, no explanation, no extra keys.

Top-level JSON shape
---------------------
{
  "container": "food" | "sleep" | "exercise" | "ignore",
  "data": { ... },
  "message_to_user": "short confirmation text in plain English"
}

Definitions
-----------
1) FOOD
   - The user is describing what they ate or drank.
   - Examples: meals, snacks, drinks, macros, calories.

   data for FOOD:
   {
     "date": "YYYY-MM-DD" or null,
     "meal_name": "string or null",
     "calories": float or null,
     "protein_g": float or null,
     "carbs_g": float or null,
     "fat_g": float or null,
     "fiber_g": float or null,
     "notes": "string or null"
   }

2) SLEEP
   - The user is describing sleep duration, quality, or energy after waking.

   data for SLEEP:
   {
     "date": "YYYY-MM-DD" or null,
     "sleep_score": float or null,
     "energy_score": float or null,
     "duration_hr": float or null,
     "resting_hr": float or null,
     "sleep_start": "YYYY-MM-DDTHH:MM:SS" or null,
     "sleep_end": "YYYY-MM-DDTHH:MM:SS" or null,
     "notes": "string or null"
   }

3) EXERCISE
   - The user is describing a workout, run, walk, or any training.

   data for EXERCISE:
   {
     "date": "YYYY-MM-DD" or null,
     "workout_name": "string or null",
     "distance_km": float or null,
     "duration_min": float or null,
     "calories_burned": float or null,
     "training_intensity": float or null,
     "avg_hr": float or null,
     "max_hr": float or null,
     "training_type": "cardio" | "strength" | "mixed" | null,
     "perceived_intensity": float or null,
     "effort_description": "string or null",
     "tags": "comma-separated tags or null",
     "notes": "string or null"
   }

4) IGNORE
   - If the message is clearly NOT a health log (e.g. “hi”, “thank you”, general chat),
     set "container": "ignore" and put a short explanation in notes.

Rules
-----
- If the user does NOT provide a date, set "date": null.
  (The backend will fill today’s date in Portugal timezone.)
- DO NOT guess macros or numbers that the user did not imply.
- For any missing field, set it to null (not 0).
- DO NOT ask the user questions. Your output is final for this message.
- The "message_to_user" should be a short confirmation like:
  - "Logged breakfast with 520 kcal."
  - "Logged 7.5 hours of sleep."
  - "Logged 5 km run."
  - "Not a log entry, nothing saved."

Container detection hints
-------------------------
- FOOD keywords: "breakfast", "lunch", "dinner", "snack", "ate", "meal", "kcal", "calories", "protein".
- SLEEP keywords: "slept", "sleep", "in bed", "woke up", "rested", "sleep score", "energy 7/10".
- EXERCISE keywords: "run", "walk", "workout", "gym", "training", "bike", "ride", "steps", "heart rate", "HR".

If more than one container is present in a single message, pick the DOMINANT one:
- Sleep dominates if the primary focus is sleep/energy.
- Exercise dominates if the primary focus is workout/running.
- Food dominates if the primary focus is meals/macros.

Output examples
---------------
Example 1 (food):
{
  "container": "food",
  "data": {
    "date": "2025-11-15",
    "meal_name": "breakfast",
    "calories": 520,
    "protein_g": 32,
    "carbs_g": 45,
    "fat_g": 18,
    "fiber_g": 8,
    "notes": "Oats with protein powder and berries"
  },
  "message_to_user": "Logged breakfast with 520 kcal and 32 g protein."
}

Example 2 (sleep):
{
  "container": "sleep",
  "data": {
    "date": "2025-11-15",
    "sleep_score": 8,
    "energy_score": 7,
    "duration_hr": 7.5,
    "resting_hr": 55,
    "sleep_start": "2025-11-14T23:30:00",
    "sleep_end": "2025-11-15T07:00:00",
    "notes": "Slept well, woke up once at night."
  },
  "message_to_user": "Logged 7.5 hours of sleep with score 8/10."
}

Example 3 (exercise):
{
  "container": "exercise",
  "data": {
    "date": "2025-11-15",
    "workout_name": "easy run",
    "distance_km": 5.0,
    "duration_min": 30,
    "calories_burned": 320,
    "training_intensity": 3,
    "avg_hr": 140,
    "max_hr": 155,
    "training_type": "cardio",
    "perceived_intensity": 3,
    "effort_description": "Comfortable, easy pace.",
    "tags": "run,outdoor",
    "notes": "Nice morning run."
  },
  "message_to_user": "Logged easy run: 5.0 km in 30 min."
}

Example 4 (ignore):
{
  "container": "ignore",
  "data": {
    "date": null,
    "notes": "General chat, not a log entry."
  },
  "message_to_user": "This was not a log entry, so nothing was saved."
}

Remember: ALWAYS output a single JSON object with exactly the keys:
- container
- data
- message_to_user
"""

# ----------------------------------------------------
# Helper: current date in Portugal (for auto-fill)
# ----------------------------------------------------
def get_today_date_str() -> str:
    now_pt = datetime.now(LISBON_TZ)
    return now_pt.date().isoformat()


# ----------------------------------------------------
# Telegram helpers
# ----------------------------------------------------
def send_telegram_message(chat_id: int | str, text: str) -> None:
    if not TELEGRAM_TOKEN:
        logging.error("TELEGRAM_BOT_TOKEN env var is missing.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        logging.info("Telegram sendMessage status=%s body=%s", resp.status_code, resp.text)
    except Exception as e:
        logging.exception("Error sending Telegram message: %s", e)


# ----------------------------------------------------
# OpenAI parser call (Responses API, no structured-output extras)
# ----------------------------------------------------
def call_gpt_parser(user_text: str) -> dict | None:
    """
    Call GPT with the parser system prompt and the user's message.
    Expect a JSON object as a string, then json.loads it.
    """
    if not OPENAI_API_KEY:
        logging.error("OPENAI_API_KEY env var is missing.")
        return None

    try:
        logging.info("GPT PARSER INPUT: %s", user_text)

        response = openai_client.responses.create(
            model="gpt-4.1-mini",
            input=[
                {
                    "role": "system",
                    "content": [
                        {"type": "input_text", "text": PARSER_SYSTEM_PROMPT}
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": user_text}
                    ],
                },
            ],
        )

        # Extract text from Responses API
        try:
            first_output = response.output[0]
            first_content = first_output.content[0]
            text_obj = getattr(first_content, "text", None)
            if text_obj is None:
                raw_text = str(first_content)
            else:
                # In the SDK, .text is usually an object with .value
                raw_text = getattr(text_obj, "value", None) or str(text_obj)
        except Exception as e:
            logging.exception("Failed to extract text from GPT response: %s", e)
            return None

        logging.info("GPT RAW OUTPUT: %s", raw_text)

        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as e:
            logging.error("GPT output is not valid JSON: %s", e)
            return None

        return parsed

    except Exception as e:
        logging.exception("GPT PARSE ERROR: %s", e)
        return None


# ----------------------------------------------------
# Supabase helper
# ----------------------------------------------------
def insert_into_supabase(table: str, payload: dict) -> tuple[bool, str]:
    """
    Insert a single row into Supabase table via REST API.
    Returns (success: bool, message: str)
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False, "Supabase env vars missing."

    url = f"{SUPABASE_URL.rstrip('/')}/{table}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    logging.info("Supabase insert → table=%s payload=%s", table, json.dumps(payload))

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        logging.info("Supabase response status=%s body=%s", resp.status_code, resp.text)

        if not resp.ok:
            return False, f"Supabase {table} insert failed: {resp.status_code} {resp.text}"

        return True, resp.text
    except Exception as e:
        logging.exception("Error calling Supabase: %s", e)
        return False, str(e)


# ----------------------------------------------------
# Container-specific handlers
# ----------------------------------------------------
def handle_food(chat_id: int | str, data: dict) -> tuple[bool, str]:
    date = data.get("date") or get_today_date_str()

    payload = {
        "chat_id": str(chat_id),  # assumes chat_id column exists
        "date": date,
        "meal_name": data.get("meal_name"),
        "calories": data.get("calories"),
        "protein_g": data.get("protein_g"),
        "carbs_g": data.get("carbs_g"),
        "fat_g": data.get("fat_g"),
        "fiber_g": data.get("fiber_g"),
        "notes": data.get("notes"),
    }

    return insert_into_supabase("food", payload)


def handle_sleep(chat_id: int | str, data: dict) -> tuple[bool, str]:
    date = data.get("date") or get_today_date_str()

    payload = {
        "chat_id": str(chat_id),
        "date": date,
        "sleep_score": data.get("sleep_score"),
        "energy_score": data.get("energy_score"),
        "duration_hr": data.get("duration_hr"),
        "resting_hr": data.get("resting_hr"),
        "sleep_start": data.get("sleep_start"),
        "sleep_end": data.get("sleep_end"),
        "notes": data.get("notes"),
    }

    return insert_into_supabase("sleep", payload)


def handle_exercise(chat_id: int | str, data: dict) -> tuple[bool, str]:
    date = data.get("date") or get_today_date_str()

    payload = {
        "chat_id": str(chat_id),
        "date": date,
        "workout_name": data.get("workout_name"),
        "distance_km": data.get("distance_km"),
        "duration_min": data.get("duration_min"),
        "calories_burned": data.get("calories_burned"),
        "training_intensity": data.get("training_intensity"),
        "avg_hr": data.get("avg_hr"),
        "max_hr": data.get("max_hr"),
        "training_type": data.get("training_type"),
        "perceived_intensity": data.get("perceived_intensity"),
        "effort_description": data.get("effort_description"),
        "tags": data.get("tags"),
        "notes": data.get("notes"),
    }

    return insert_into_supabase("exercise", payload)


# ----------------------------------------------------
# Telegram webhook
# ----------------------------------------------------
@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    try:
        update = request.get_json(force=True, silent=True) or {}
        logging.info("Incoming Telegram update: %s", json.dumps(update))

        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat", {}) or {}
        chat_id = chat.get("id")
        user_text = message.get("text", "")

        if not chat_id:
            logging.error("No chat_id in update.")
            return "no chat id", 200

        if not user_text:
            # For now we ignore non-text updates (photos, audio, etc.)
            send_telegram_message(chat_id, "I only support text logs for now.")
            return "ok", 200

        # 1) Call GPT parser
        parsed = call_gpt_parser(user_text)
        if parsed is None:
            send_telegram_message(chat_id, "⚠️ Sorry, I could not process that message.")
            return "ok", 200

        container = parsed.get("container")
        data = parsed.get("data") or {}
        message_to_user = parsed.get("message_to_user") or "Done."

        logging.info("Parsed container=%s data=%s", container, json.dumps(data))

        # 2) Route to correct handler
        if container == "food":
            success, info = handle_food(chat_id, data)
            if success:
                send_telegram_message(chat_id, message_to_user)
            else:
                send_telegram_message(
                    chat_id,
                    f"{message_to_user}\n\nHowever, saving to food failed: {info}",
                )
            return "ok", 200

        if container == "sleep":
            success, info = handle_sleep(chat_id, data)
            if success:
                send_telegram_message(chat_id, message_to_user)
            else:
                send_telegram_message(
                    chat_id,
                    f"{message_to_user}\n\nHowever, saving to sleep failed: {info}",
                )
            return "ok", 200

        if container == "exercise":
            success, info = handle_exercise(chat_id, data)
            if success:
                send_telegram_message(chat_id, message_to_user)
            else:
                send_telegram_message(
                    chat_id,
                    f"{message_to_user}\n\nHowever, saving to exercise failed: {info}",
                )
            return "ok", 200

        if container == "ignore":
            # Just echo the message_to_user, no DB insert
            send_telegram_message(chat_id, message_to_user)
            return "ok", 200

        # Fallback: unknown container
        send_telegram_message(
            chat_id,
            "I could not classify this as food, sleep, or exercise, so nothing was saved.",
        )
        return "ok", 200

    except Exception as e:
        logging.exception("WEBHOOK ERROR: %s", e)
        return "ok", 200


# ----------------------------------------------------
# Health check
# ----------------------------------------------------
@app.route("/", methods=["GET"])
def home():
    return "OK", 200


if __name__ == "__main__":
    # Local dev only. Render uses gunicorn.
    app.run(host="0.0.0.0", port=10000)
