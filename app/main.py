import os
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from flask import Flask, request
from openai import OpenAI

# --------------------------------------------------
# Basic setup
# --------------------------------------------------

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY")
GPT_PROMPT_ID = os.environ.get("GPT_PROMPT_ID")  # optional; falls back to gpt-4.1-mini

openai_client = OpenAI(api_key=OPENAI_API_KEY)

# --------------------------------------------------
# Helpers
# --------------------------------------------------

def get_local_date_iso():
    """
    Return today's date in Europe/Lisbon as YYYY-MM-DD.
    No external deps (uses stdlib zoneinfo).
    """
    tz = ZoneInfo("Europe/Lisbon")
    return datetime.now(tz).date().isoformat()


def send_telegram_message(chat_id: int | str, text: str):
    """
    Send a plain-text message back to the Telegram user.
    """
    if not TELEGRAM_TOKEN:
        logging.error("TELEGRAM_TOKEN missing - cannot send Telegram messages.")
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
        logging.error("Telegram sendMessage error: %s", e)


def call_gpt_parser(user_text: str):
    """
    Call OpenAI Responses API to classify the message and extract structured data.

    Expected JSON shape from the model:

    {
      "container": "food" | "sleep" | "exercise" | "unknown",
      "data": { ... },
      "message_to_user": "short confirmation string"
    }
    """
    if not OPENAI_API_KEY:
        logging.error("OPENAI_API_KEY missing, cannot call GPT.")
        return None

    model_id = GPT_PROMPT_ID or "gpt-4.1-mini"

    system_prompt = (
        "You are YAHA's ingestion parser.\n"
        "Your job is to read a single Telegram message and decide if it is about:\n"
        "- food\n"
        "- sleep\n"
        "- exercise\n"
        "Then you must output ONE JSON object only (no markdown, no extra text), with this shape:\n"
        "{\n"
        '  \"container\": \"food\" | \"sleep\" | \"exercise\" | \"unknown\",\n"
        "  \"data\": { ... },\n"
        "  \"message_to_user\": \"short natural-language confirmation\"\n"
        "}\n"
        "\n"
        "For container = \"food\", the data object may include:\n"
        "  \"date\" (YYYY-MM-DD or null),\n"
        "  \"meal_name\",\n"
        "  \"calories\",\n"
        "  \"protein_g\",\n"
        "  \"carbs_g\",\n"
        "  \"fat_g\",\n"
        "  \"fiber_g\",\n"
        "  \"notes\".\n"
        "\n"
        "For container = \"sleep\", the data object may include:\n"
        "  \"date\" (YYYY-MM-DD or null),\n"
        "  \"sleep_score\",\n"
        "  \"energy_score\",\n"
        "  \"duration_hr\",\n"
        "  \"resting_hr\",\n"
        "  \"sleep_start\",\n"
        "  \"sleep_end\",\n"
        "  \"notes\".\n"
        "\n"
        "For container = \"exercise\", the data object may include:\n"
        "  \"date\" (YYYY-MM-DD or null),\n"
        "  \"workout_name\",\n"
        "  \"distance_km\",\n"
        "  \"duration_min\",\n"
        "  \"calories_burned\",\n"
        "  \"training_intensity\",\n"
        "  \"avg_hr\",\n"
        "  \"max_hr\",\n"
        "  \"training_type\",\n"
        "  \"perceived_intensity\",\n"
        "  \"effort_description\",\n"
        "  \"tags\",\n"
        "  \"notes\".\n"
        "\n"
        "Rules:\n"
        "- Use numbers as bare numbers (no units attached).\n"
        "- If the user does not clearly give a date, set \"date\" to null.\n"
        "- For any field you cannot safely infer, use null.\n"
        "- If the message is not clearly food, sleep or exercise, set \"container\" to \"unknown\".\n"
        "- Absolutely do NOT wrap the JSON in ``` or any other formatting.\n"
    )

    try:
        logging.info("GPT PARSER INPUT: %s", user_text)

        response = openai_client.responses.create(
            model=model_id,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
        )

        # Extract plain text from Responses API
        try:
            raw_text = response.output[0].content[0].text
        except Exception as e:
            logging.error("Unexpected GPT response structure: %s", e)
            logging.error("Full GPT response: %s", response)
            return None

        logging.info("GPT RAW OUTPUT: %s", raw_text)

        # Try to parse JSON
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as e:
            logging.error("Failed to json.loads GPT output: %s", e)
            return None

        # Sometimes models return a list like [ {..} ], handle that too.
        if isinstance(parsed, list) and parsed:
            parsed = parsed[0]

        if not isinstance(parsed, dict):
            logging.error("Parsed GPT output is not a dict: %s", type(parsed))
            return None

        return parsed

    except Exception as e:
        logging.error("GPT PARSER ERROR: %s", e)
        return None


def supabase_insert(table: str, row: dict):
    """
    Insert a single row into Supabase and return (ok, status_code, text).
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        logging.error("Supabase env vars missing.")
        return False, 0, "Supabase URL or key missing"

    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    try:
        logging.info("Supabase insert -> table=%s payload=%s", table, row)
        resp = requests.post(url, headers=headers, json=row, timeout=10)
        logging.info("Supabase response status=%s body=%s", resp.status_code, resp.text)
        ok = 200 <= resp.status_code < 300
        return ok, resp.status_code, resp.text
    except Exception as e:
        logging.error("Supabase insert error: %s", e)
        return False, 0, str(e)


def build_payload(container: str, data: dict, chat_id: int | str):
    """
    Add common fields (user_id, chat_id, date) and filter allowed columns
    for each table so we don't send unknown columns to Supabase.
    """
    if data is None:
        data = {}

    # For MVP: user_id == chat_id as string
    user_id = str(chat_id)

    # Auto-fill date if missing or null
    date_val = data.get("date")
    if not date_val:
        date_val = get_local_date_iso()

    base = {
        "user_id": user_id,
        "chat_id": str(chat_id),
        "date": date_val,
    }

    if container == "food":
        allowed = [
            "user_id",
            "chat_id",
            "date",
            "meal_name",
            "calories",
            "protein_g",
            "carbs_g",
            "fat_g",
            "fiber_g",
            "notes",
            "foodbank_item_id",
        ]
    elif container == "sleep":
        allowed = [
            "user_id",
            "chat_id",
            "date",
            "sleep_score",
            "energy_score",
            "duration_hr",
            "resting_hr",
            "sleep_start",
            "sleep_end",
            "notes",
        ]
    elif container == "exercise":
        allowed = [
            "user_id",
            "chat_id",
            "date",
            "workout_name",
            "distance_km",
            "duration_min",
            "calories_burned",
            "training_intensity",
            "avg_hr",
            "max_hr",
            "training_type",
            "perceived_intensity",
            "effort_description",
            "tags",
            "notes",
        ]
    else:
        return None  # unknown container

    merged = {**data, **base}  # data wins, then we overwrite with base for core fields
    filtered = {k: merged.get(k) for k in allowed if k in merged}
    return filtered


# --------------------------------------------------
# Webhook
# --------------------------------------------------

@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    try:
        update = request.get_json(force=True)
        logging.info("Incoming Telegram update: %s", update)

        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        user_text = message.get("text") or ""

        if not chat_id:
            logging.error("No chat_id found in update.")
            return "no chat id", 200

        if not user_text:
            send_telegram_message(chat_id, "I only understand text messages for now.")
            return "ok", 200

        parsed = call_gpt_parser(user_text)
        if not parsed:
            send_telegram_message(chat_id, "⚠️ Sorry, I couldn't process that message.")
            return "ok", 200

        container = parsed.get("container")
        data = parsed.get("data") or {}
        message_to_user = parsed.get("message_to_user") or "Got it."

        # If GPT couldn't classify, don't hit Supabase.
        if container not in ("food", "sleep", "exercise"):
            send_telegram_message(
                chat_id,
                "I couldn't figure out if this was food, sleep or exercise.\n"
                "Please tell me which one you're trying to log."
            )
            return "ok", 200

        payload = build_payload(container, data, chat_id)
        if payload is None:
            send_telegram_message(
                chat_id,
                "Something went wrong preparing your log. Try rephrasing or specifying the type (food / sleep / exercise)."
            )
            return "ok", 200

        ok, status_code, body_text = supabase_insert(container, payload)

        if ok:
            # Success – just send the friendly confirmation.
            send_telegram_message(chat_id, message_to_user)
        else:
            # Partial fail – tell user we understood, but DB write failed.
            error_msg = (
                f"{message_to_user}\n\n"
                f"However, saving to {container} failed: "
                f"Supabase {container} insert failed: {status_code} {body_text}"
            )
            send_telegram_message(chat_id, error_msg)

        return "ok", 200

    except Exception as e:
        logging.error("WEBHOOK ERROR: %s", e)
        return "ok", 200


# --------------------------------------------------
# Health check
# --------------------------------------------------

@app.route("/", methods=["GET"])
def home():
    return "OK", 200


if __name__ == "__main__":
    # Local dev
    app.run(host="0.0.0.0", port=10000)
