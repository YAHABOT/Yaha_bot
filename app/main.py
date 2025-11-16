import os
from flask import Flask, request
from openai import OpenAI
import requests
import json
from datetime import datetime
from zoneinfo import ZoneInfo  # built-in replacement for pytz

app = Flask(__name__)

# -------------------------------
# Environment variables
# -------------------------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY")
GPT_PROMPT_ID = os.environ.get("GPT_PROMPT_ID")

openai_client = OpenAI(api_key=OPENAI_API_KEY)

PORTUGAL_TZ = ZoneInfo("Europe/Lisbon")


# -------------------------------
# Telegram Helpers
# -------------------------------
def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    requests.post(url, json=payload)


# -------------------------------
# GPT PARSER v3 (container detection + JSON)
# -------------------------------
def call_gpt_parser(prompt):
    try:
        response = openai_client.responses.parse(
            model="gpt-4.1-mini",
            input=prompt,
        )
        return response.output

    except Exception as e:
        print("GPT PARSE ERROR:", e)
        return None


# -------------------------------
# Utility: get today's date in Portugal
# -------------------------------
def get_local_date():
    return datetime.now(PORTUGAL_TZ).strftime("%Y-%m-%d")


# -------------------------------
# Utility: Supabase POST Wrapper
# -------------------------------
def supabase_insert(table, row):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    r = requests.post(url, headers=headers, json=row)

    if r.status_code >= 300:
        print(f"SUPABASE ERROR ({table}):", r.text)
    else:
        print(f"SUPABASE OK ({table}):", r.text)

    return r.status_code, r.text


# -------------------------------
# /webhook — MAIN INGESTION ENTRY
# -------------------------------
@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    try:
        update = request.get_json()
        message = update.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        user_text = message.get("text", "")

        if not chat_id:
            return "no chat id", 200

        parsed = call_gpt_parser(user_text)

        if parsed is None:
            send_telegram_message(chat_id, "⚠️ Sorry, I couldn’t process that.")
            return "ok", 200

        # String → just echo it
        if isinstance(parsed, str):
            send_telegram_message(chat_id, parsed)
            return "ok", 200

        # -------------------------------
        # JSON_OUTPUT → container logic
        # -------------------------------
        container = parsed.get("container")

        if not container:
            send_telegram_message(chat_id, "I didn’t understand what to log. Food, sleep, or exercise?")
            return "ok", 200

        # Force user_id = chat_id (temporary rule)
        parsed["user_id"] = str(chat_id)
        parsed["chat_id"] = str(chat_id)

        # Auto-fill date if missing
        if "date" not in parsed or not parsed["date"]:
            parsed["date"] = get_local_date()

        # Insert into Supabase
        status, resp = supabase_insert(container, parsed)

        if status < 300:
            send_telegram_message(chat_id, f"Logged your {container} entry 👍")
        else:
            send_telegram_message(chat_id, f"⚠️ Error logging {container}. Check logs.")

        return "ok", 200

    except Exception as e:
        print("WEBHOOK ERROR:", e)
        return "ok", 200


# -------------------------------
# Health check
# -------------------------------
@app.route("/", methods=["GET"])
def home():
    return "OK", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
