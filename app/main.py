import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from flask import Flask, request
from openai import OpenAI

# -------------------------------
# App & config
# -------------------------------

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY")

# Single-owner mapping (MVP)
OWNER_CHAT_ID = os.environ.get("YAHA_OWNER_CHAT_ID")      # e.g. "2052083060"
OWNER_USER_ID = os.environ.get("YAHA_OWNER_USER_ID")      # e.g. your UUID from Supabase users table

# Timezone for "today"
LOCAL_TZ = ZoneInfo("Europe/Lisbon")

openai_client = OpenAI(api_key=OPENAI_API_KEY)


# -------------------------------
# Helpers
# -------------------------------

def today_local_date_str() -> str:
    """Return today's date as YYYY-MM-DD in Europe/Lisbon."""
    return datetime.now(LOCAL_TZ).date().isoformat()


def now_utc_iso() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.utcnow().isoformat() + "Z"


def send_telegram_message(chat_id, text):
    """Send a plain text message to Telegram."""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
        }
        resp = requests.post(url, json=payload, timeout=10)
        print(f"[TELEGRAM] status={resp.status_code} body={resp.text}")
    except Exception as e:
        print(f"[TELEGRAM ERROR] {e}")


def supabase_insert(table: str, row: dict):
    """Insert one row into Supabase using REST API."""
    try:
        url = f"{SUPABASE_URL}/rest/v1/{table}"
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        resp = requests.post(url, headers=headers, json=row, timeout=10)
        print(f"[SUPABASE {table}] status={resp.status_code} body={resp.text}")
        return resp
    except Exception as e:
        print(f"[SUPABASE ERROR] table={table} error={e}")
        return None


# -------------------------------
# GPT parser
# -------------------------------

PARSER_SYSTEM_PROMPT = """
You are the YAHA ingestion parser.

Your job:
1. Decide which container the user is logging into: "food", "sleep", "exercise", or "unknown".
2. Extract structured fields into a JSON object that matches the container.
3. Generate a short friendly reply for the Telegram user confirming what was logged.

You MUST respond with VALID JSON ONLY, no extra text, no explanations.

JSON SCHEMA (conceptual, not strict):

{
  "container": "food" | "sleep" | "exercise" | "unknown",
  "data": {
    // for container == "food":
    //   "date": "YYYY-MM-DD" (optional, if missing use today),
    //   "meal_name": string,
    //   "calories": number or string,
    //   "protein_g": number or string,
    //   "carbs_g": number or string,
    //   "fat_g": number or string,
    //   "fiber_g": number or string,
    //   "notes": string

    // for container == "sleep":
    //   "date": "YYYY-MM-DD" (optional, if missing use today),
    //   "sleep_score": number or string,
    //   "energy_score": number or string,
    //   "duration_hr": number or string,
    //   "resting_hr": number or string,
    //   "sleep_start": string (optional, free text or time),
    //   "sleep_end": string (optional, free text or time),
    //   "notes": string

    // for container == "exercise":
    //   "date": "YYYY-MM-DD" (optional, if missing use today),
    //   "workout_name": string,
    //   "distance_km": number or string,
    //   "duration_min": number or string,
    //   "calories_burned": number or string,
    //   "training_intensity": string or number,
    //   "avg_hr": number or string,
    //   "max_hr": number or string,
    //   "training_type": string (e.g. cardio, strength),
    //   "perceived_intensity": number or string,
    //   "effort_description": string,
    //   "tags": string,
    //   "notes": string
  },
  "reply_text": "short confirmation message to send back to the user"
}

RULES:

- If the message is clearly about FOOD (meals, calories, macros, breakfast/lunch/dinner/snack) → container = "food".
- If it is clearly about SLEEP (hours slept, sleep quality, sleep score, energy on waking) → container = "sleep".
- If it is clearly about EXERCISE (run, walk, gym, workout, distance, pace, sets, reps, calories burned, heart rate) → container = "exercise".
- If it's unclear → container = "unknown" and set reply_text to ask the user what they are trying to log.

- Do NOT invent macros or numbers unless the user mentions them or it is a very standard inference (e.g. "5 km run in 30 minutes" → distance_km, duration_min).
- It is OK to leave fields out of "data" if the user didn’t provide them.
- Do NOT guess the date; if user doesn’t give a date, omit it and let the backend fill "today".
"""


def call_gpt_parser(user_text: str, chat_id: int | str):
    """Call GPT to classify + extract fields into JSON."""
    try:
        chat_id_str = str(chat_id)
        messages = [
            {"role": "system", "content": PARSER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Telegram chat_id: {chat_id_str}\nUser message: {user_text}",
            },
        ]

        completion = openai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=messages,
            temperature=0.1,
        )

        raw = completion.choices[0].message.content
        print(f"[GPT RAW] {raw}")

        parsed = json.loads(raw)
        return parsed

    except json.JSONDecodeError as e:
        print(f"[GPT PARSE ERROR] JSON decode failed: {e}")
        return None
    except Exception as e:
        print(f"[GPT ERROR] {e}")
        return None


# -------------------------------
# Webhook
# -------------------------------

@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    try:
        update = request.get_json(force=True, silent=True) or {}
        print(f"[WEBHOOK] Incoming update: {json.dumps(update)}")

        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        user_text = message.get("text", "").strip()

        if not chat_id:
            print("[WEBHOOK] No chat_id in update")
            return "no chat id", 200

        if not user_text:
            send_telegram_message(chat_id, "I only understand text logs for now.")
            return "ok", 200

        # 1) Ask GPT to classify + extract fields
        parsed = call_gpt_parser(user_text, chat_id)
        if not parsed:
            send_telegram_message(chat_id, "⚠️ Sorry, I couldn’t process that. Try rephrasing?")
            return "ok", 200

        container = parsed.get("container", "unknown")
        data = parsed.get("data", {}) or {}
        reply_text = parsed.get("reply_text") or "Got it, thanks!"

        # 2) Common fields
        chat_id_str = str(chat_id)
        today_str = today_local_date_str()
        now_utc = now_utc_iso()

        # user_id mapping (MVP: single owner)
        user_id = None
        if OWNER_CHAT_ID and OWNER_USER_ID and chat_id_str == OWNER_CHAT_ID:
            user_id = OWNER_USER_ID

        # helper to get date from data or default
        date_val = data.get("date") or today_str

        # 3) Route to correct container
        if container == "food":
            row = {
                "user_id": user_id,
                "chat_id": chat_id_str,
                "date": date_val,
                "meal_name": data.get("meal_name"),
                "calories": data.get("calories"),
                "protein_g": data.get("protein_g"),
                "carbs_g": data.get("carbs_g"),
                "fat_g": data.get("fat_g"),
                "fiber_g": data.get("fiber_g"),
                "notes": data.get("notes"),
                "created_at": now_utc,
                "recorded_at": now_utc,
            }
            resp = supabase_insert("food", row)
            if not resp or resp.status_code >= 400:
                send_telegram_message(chat_id, "⚠️ I tried to log your food but Supabase returned an error.")
            else:
                send_telegram_message(chat_id, reply_text)
            return "ok", 200

        elif container == "sleep":
            row = {
                "user_id": user_id,
                "chat_id": chat_id_str,
                "date": date_val,
                "sleep_score": data.get("sleep_score"),
                "energy_score": data.get("energy_score"),
                "duration_hr": data.get("duration_hr"),
                "resting_hr": data.get("resting_hr"),
                "sleep_start": data.get("sleep_start"),
                "sleep_end": data.get("sleep_end"),
                "notes": data.get("notes"),
                "created_at": now_utc,
                "recorded_at": now_utc,
            }
            resp = supabase_insert("sleep", row)
            if not resp or resp.status_code >= 400:
                send_telegram_message(chat_id, "⚠️ I tried to log your sleep but Supabase returned an error.")
            else:
                send_telegram_message(chat_id, reply_text)
            return "ok", 200

        elif container == "exercise":
            row = {
                "user_id": user_id,
                "chat_id": chat_id_str,
                "date": date_val,
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
                "created_at": now_utc,
                "recorded_at": now_utc,
            }
            resp = supabase_insert("exercise", row)
            if not resp or resp.status_code >= 400:
                send_telegram_message(chat_id, "⚠️ I tried to log your exercise but Supabase returned an error.")
            else:
                send_telegram_message(chat_id, reply_text)
            return "ok", 200

        else:
            # Unknown container
            send_telegram_message(
                chat_id,
                "I’m not sure if that was food, sleep, or exercise.\n"
                "What are you trying to log?"
            )
            return "ok", 200

    except Exception as e:
        print(f"[WEBHOOK ERROR] {e}")
        try:
            send_telegram_message(chat_id, "⚠️ Something went wrong on my side.")
        except Exception:
            pass
        return "ok", 200


# -------------------------------
# Health check
# -------------------------------

@app.route("/", methods=["GET"])
def home():
    return "OK", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
