import os
from flask import Flask, request
from openai import OpenAI
import requests
import json
from datetime import datetime
import pytz

app = Flask(__name__)

# ---------------------------------------------------------
# ENVIRONMENT VARIABLES
# ---------------------------------------------------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY")
GPT_PROMPT_ID = os.environ.get("GPT_PROMPT_ID")

openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Portugal timezone (user local time)
PT_TZ = pytz.timezone("Europe/Lisbon")


# ---------------------------------------------------------
# TELEGRAM SEND FUNCTION
# ---------------------------------------------------------
def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    requests.post(url, json=payload)


# ---------------------------------------------------------
# GPT PARSER USING NEW RESPONSES PARSE API
# ---------------------------------------------------------
def call_gpt_parser(prompt: str):
    try:
        response = openai_client.responses.parse(
            model="gpt-4.1-mini",
            input=prompt,
            instruction=f"Use parser: {GPT_PROMPT_ID}"
        )
        return response.output
    except Exception as e:
        print("GPT PARSE ERROR:", e)
        return None


# ---------------------------------------------------------
# SUPABASE INSERT HELPER
# ---------------------------------------------------------
def insert_into_supabase(table: str, payload: dict):
    try:
        url = f"{SUPABASE_URL}/{table}"
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json"
        }

        r = requests.post(url, headers=headers, json=payload)

        print("SUPABASE INSERT RESPONSE:", r.status_code, r.text)

        return r.status_code in (200, 201)
    except Exception as e:
        print("SUPABASE INSERT ERROR:", e)
        return False


# ---------------------------------------------------------
# AUTO CONTAINER DETECTION
# ---------------------------------------------------------
def detect_container(text: str):
    t = text.lower()

    # Strong FOOD keywords
    if any(w in t for w in ["kcal", "calories", "protein", "carbs", "fat", "ate", "meal",
                            "breakfast", "lunch", "dinner", "snack"]):
        return "food"

    # Strong SLEEP keywords
    if any(w in t for w in ["slept", "sleep", "rem", "deep sleep", "resting hr"]):
        return "sleep"

    # Strong EXERCISE keywords
    if any(w in t for w in ["run", "ran", "walking", "walked", "km", "pace",
                            "workout", "gym", "exercise", "sets", "reps", "hr"]):
        return "exercise"

    return None


# ---------------------------------------------------------
# BUILD PAYLOAD FOR SUPABASE (ADD user_id + auto date)
# ---------------------------------------------------------
def build_payload(chat_id, parsed: dict):
    # Auto-fill date based on Portugal time
    now_pt = datetime.now(PT_TZ).date()

    payload = {
        "chat_id": str(chat_id),
        "user_id": str(chat_id),   # <-- FIXED HERE
        "date": parsed.get("date", str(now_pt))
    }

    # Merge in all GPT fields (skips date & user_id)
    for key, value in parsed.items():
        if key not in ["user_id"]:
            payload[key] = value

    return payload


# ---------------------------------------------------------
# TELEGRAM WEBHOOK
# ---------------------------------------------------------
@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    try:
        update = request.get_json()
        print("INCOMING UPDATE:", json.dumps(update))

        message = update.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        user_text = message.get("text", "")

        if not chat_id:
            return "no chat id", 200

        # 1️⃣ Auto-detect container
        detected = detect_container(user_text)

        # 2️⃣ Parse with GPT
        parsed = call_gpt_parser(user_text)
        print("GPT PARSED:", parsed)

        if not parsed:
            send_telegram_message(chat_id, "⚠️ Sorry, I couldn’t process that.")
            return "ok", 200

        # If GPT returns text → send it
        if isinstance(parsed, str):
            send_telegram_message(chat_id, parsed)
            return "ok", 200

        # Must be dict for container inserts
        if not isinstance(parsed, dict):
            send_telegram_message(chat_id, str(parsed))
            return "ok", 200

        # 3️⃣ Determine container (if GPT already labels it)
        container = parsed.get("container") or detected

        if not container:
            send_telegram_message(
                chat_id,
                "I’m not sure if this is food, exercise, or sleep.\nWhich one is it?"
            )
            return "ok", 200

        # 4️⃣ Build proper payload with user_id + date
        payload = build_payload(chat_id, parsed)

        # 5️⃣ Insert into Supabase
        success = insert_into_supabase(container, payload)

        if success:
            send_telegram_message(chat_id, f"✅ Logged to *{container}* successfully.")
        else:
            send_telegram_message(chat_id, f"❌ Failed to log {container}. Check logs.")

        return "ok", 200

    except Exception as e:
        print("WEBHOOK ERROR:", e)
        return "ok", 200


# ---------------------------------------------------------
# HEALTH CHECK
# ---------------------------------------------------------
@app.route("/", methods=["GET"])
def home():
    return "OK", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
