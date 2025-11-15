import os
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import requests
from flask import Flask, request, jsonify
from openai import OpenAI, OpenAIError

# -----------------------------------------------------------------------------
# Flask app & logging
# -----------------------------------------------------------------------------

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# -----------------------------------------------------------------------------
# Environment
# -----------------------------------------------------------------------------

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_API_KEY = os.environ.get("SUPABASE_ANON_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
GPT_PROMPT_ID = os.environ.get("GPT_PROMPT_ID")  # currently not used, kept for future use

if not SUPABASE_URL or not SUPABASE_API_KEY or not TELEGRAM_BOT_TOKEN or not OPENAI_API_KEY:
    logging.warning(
        "Some critical environment variables are missing. "
        "The application may not function correctly."
    )

# OpenAI client
openai_client = OpenAI(api_key=OPENAI_API_KEY)


# -----------------------------------------------------------------------------
# Helper: Telegram
# -----------------------------------------------------------------------------

def send_telegram_message(chat_id: int, text: str) -> Optional[requests.Response]:
    """Send a plain text message back to the Telegram user."""
    if not TELEGRAM_BOT_TOKEN:
        logging.error("TELEGRAM_BOT_TOKEN not configured.")
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        logging.info("Telegram sendMessage status=%s body=%s", resp.status_code, resp.text)
        return resp
    except Exception as exc:  # noqa: BLE001
        logging.exception("Error sending Telegram message: %s", exc)
        return None


# -----------------------------------------------------------------------------
# Helper: Supabase
# -----------------------------------------------------------------------------

def supabase_insert(table: str, payload: Dict[str, Any]) -> Optional[requests.Response]:
    """Insert a single record into a Supabase table via REST."""
    if not SUPABASE_URL or not SUPABASE_API_KEY:
        logging.error("Supabase configuration missing; cannot insert into %s", table)
        return None

    url = f"{SUPABASE_URL}/{table}"
    headers = {
        "apikey": SUPABASE_API_KEY,
        "Authorization": f"Bearer {SUPABASE_API_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        logging.info("Supabase insert table=%s status=%s body=%s", table, resp.status_code, resp.text)
        return resp
    except Exception as exc:  # noqa: BLE001
        logging.exception("Error inserting into Supabase table=%s: %s", table, exc)
        return None


# -----------------------------------------------------------------------------
# Helper: GPT parsing
# -----------------------------------------------------------------------------

PARSER_SYSTEM_PROMPT = """
You are the logging parser for the YAHA health tracker.

Your job:
1. Decide if a Telegram message is about FOOD, SLEEP, EXERCISE, or UNKNOWN.
2. Extract structured fields for the chosen container.
3. Always respond with a single JSON object, no explanations, no extra keys.

JSON schema (all keys MUST be present; use null when unknown):

{
  "container": "food" | "sleep" | "exercise" | "unknown",

  "food": {
    "date": "YYYY-MM-DD or null",
    "meal_name": "string or null",
    "calories": "number or null",
    "protein_g": "number or null",
    "carbs_g": "number or null",
    "fat_g": "number or null",
    "fiber_g": "number or null",
    "notes": "string or null"
  },

  "sleep": {
    "date": "YYYY-MM-DD or null",
    "sleep_score": "number or null",
    "energy_score": "number or null",
    "duration_hr": "number or null",
    "resting_hr": "number or null",
    "sleep_start": "HH:MM or null",
    "sleep_end": "HH:MM or null",
    "notes": "string or null"
  },

  "exercise": {
    "date": "YYYY-MM-DD or null",
    "workout_name": "string or null",
    "distance_km": "number or null",
    "duration_min": "number or null",
    "calories_burned": "number or null",
    "avg_hr": "number or null",
    "max_hr": "number or null",
    "training_type": "string or null",
    "training_intensity": "number or null",
    "perceived_intensity": "number or null",
    "effort_description": "string or null",
    "tags": "string or null",
    "notes": "string or null"
  },

  "reply_text": "short human summary to show the user in chat"
}

Rules:
- If no explicit date is mentioned, assume today's date (UTC) and fill date with today's date.
- If the message clearly is not health tracking, set "container": "unknown".
- Never invent macros or heart-rate numbers; if they are not given, leave them null.
- If the user gives macros or HR numbers, parse them carefully and convert to numbers.
- Output MUST be valid JSON and must match the schema above.
"""


def call_gpt_parser(user_text: str) -> Dict[str, Any]:
    """Call OpenAI Responses API to classify and parse the Telegram text."""
    try:
        response = openai_client.responses.create(
            model="gpt-4.1-mini",
            response_format={"type": "json_object"},
            input=[
                {
                    "role": "system",
                    "content": PARSER_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": user_text,
                },
            ],
        )
    except OpenAIError as exc:
        logging.exception("OpenAI API error: %s", exc)
        raise

    # New SDK has a convenience property output_text for text-only responses.
    raw = getattr(response, "output_text", None)
    if not raw:
        # Fallback: best-effort extraction from first output item.
        try:
            first_output = response.output[0]
            first_content = first_output.content[0]
            raw = first_content.text  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            logging.exception("Failed to extract text from OpenAI response: %s", exc)
            raise RuntimeError("Unable to read OpenAI response text") from exc

    logging.info("OpenAI raw JSON: %s", raw)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:  # noqa: BLE001
        logging.exception("Failed to decode JSON from OpenAI: %s", exc)
        raise

    return parsed


# -----------------------------------------------------------------------------
# Mapping from parsed JSON -> Supabase payloads
# -----------------------------------------------------------------------------

def build_food_payload(chat_id: int, parsed: Dict[str, Any]) -> Dict[str, Any]:
    food = parsed.get("food") or {}
    today = datetime.utcnow().date().isoformat()
    date_value = food.get("date") or today

    return {
        # user_id left as NULL for now (handled by Supabase default)
        "date": date_value,
        "meal_name": food.get("meal_name"),
        "calories": food.get("calories"),
        "protein_g": food.get("protein_g"),
        "carbs_g": food.get("carbs_g"),
        "fat_g": food.get("fat_g"),
        "fiber_g": food.get("fiber_g"),
        "notes": food.get("notes"),
        "recorded_at": datetime.utcnow().isoformat(),
    }


def build_sleep_payload(chat_id: int, parsed: Dict[str, Any]) -> Dict[str, Any]:
    sleep = parsed.get("sleep") or {}
    today = datetime.utcnow().date().isoformat()
    date_value = sleep.get("date") or today

    return {
        "date": date_value,
        "sleep_score": sleep.get("sleep_score"),
        "energy_score": sleep.get("energy_score"),
        "duration_hr": sleep.get("duration_hr"),
        "resting_hr": sleep.get("resting_hr"),
        "sleep_start": sleep.get("sleep_start"),
        "sleep_end": sleep.get("sleep_end"),
        "notes": sleep.get("notes"),
        "recorded_at": datetime.utcnow().isoformat(),
    }


def build_exercise_payload(chat_id: int, parsed: Dict[str, Any]) -> Dict[str, Any]:
    exercise = parsed.get("exercise") or {}
    today = datetime.utcnow().date().isoformat()
    date_value = exercise.get("date") or today

    return {
        "date": date_value,
        "workout_name": exercise.get("workout_name"),
        "distance_km": exercise.get("distance_km"),
        "duration_min": exercise.get("duration_min"),
        "calories_burned": exercise.get("calories_burned"),
        "avg_hr": exercise.get("avg_hr"),
        "max_hr": exercise.get("max_hr"),
        "training_type": exercise.get("training_type"),
        "training_intensity": exercise.get("training_intensity"),
        "perceived_intensity": exercise.get("perceived_intensity"),
        "effort_description": exercise.get("effort_description"),
        "tags": exercise.get("tags"),
        "notes": exercise.get("notes"),
        "recorded_at": datetime.utcnow().isoformat(),
    }


def insert_entries_log(
    chat_id: int,
    user_text: str,
    parsed_json: Dict[str, Any],
    ai_response_text: str,
) -> None:
    """Insert a row into the public.entries table as the audit log."""
    payload = {
        "chat_id": str(chat_id),
        "user_message": user_text,
        "ai_response": ai_response_text,
        "parsed": parsed_json.get("container") != "unknown",
        "parsed_json": parsed_json,
        "recorded_at": datetime.utcnow().isoformat(),
    }
    supabase_insert("entries", payload)


# -----------------------------------------------------------------------------
# Telegram webhook
# -----------------------------------------------------------------------------

@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    data = request.get_json(force=True, silent=True) or {}
    logging.info("Incoming Telegram update: %s", json.dumps(data))

    message = data.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")

    if chat_id is None:
        logging.warning("Update without chat_id; ignoring.")
        return jsonify({"status": "ignored"}), 200

    # We only support text messages in this version.
    user_text = (message.get("text") or "").strip()
    if not user_text:
        send_telegram_message(chat_id, "At the moment I only understand text messages for logging.")
        return jsonify({"status": "ignored"}), 200

    # Special commands
    if user_text.startswith("/start"):
        send_telegram_message(
            chat_id,
            "YAHA bot is online. Send me food, sleep or workout logs in plain language, "
            "and I will store them for you.",
        )
        return jsonify({"status": "ok"}), 200

    # Call GPT to classify and parse
    try:
        parsed = call_gpt_parser(user_text)
    except Exception as exc:  # noqa: BLE001
        logging.exception("Parser failed, returning error to user: %s", exc)
        send_telegram_message(chat_id, "Sorry, I could not understand this entry. Please try again.")
        return jsonify({"status": "error"}), 200

    container = parsed.get("container", "unknown")
    reply_text = parsed.get("reply_text") or f"Logged as: {container}"

    # Always log raw entry in entries table
    insert_entries_log(chat_id, user_text, parsed, json.dumps(parsed))

    # Insert into the relevant container table
    if container == "food":
        payload = build_food_payload(chat_id, parsed)
        supabase_insert("food", payload)
    elif container == "sleep":
        payload = build_sleep_payload(chat_id, parsed)
        supabase_insert("sleep", payload)
    elif container == "exercise":
        payload = build_exercise_payload(chat_id, parsed)
        supabase_insert("exercise", payload)
    else:
        logging.info("Container=unknown; no container table insert.")

    # Reply back to user
    send_telegram_message(chat_id, reply_text)

    return jsonify({"status": "ok"}), 200


@app.route("/", methods=["GET"])
def healthcheck():
    return "YAHA bot online.", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
