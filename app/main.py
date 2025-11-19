import os
import requests
from flask import Flask, request
from openai import OpenAI
from datetime import datetime
import pytz
import json

app = Flask(__name__)

# Environment variables
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY")
GPT_PROMPT_ID = os.environ.get("GPT_PROMPT_ID")  # responses prompt

client = OpenAI(api_key=OPENAI_API_KEY)

# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def lisbon_date():
    tz = pytz.timezone("Europe/Lisbon")
    return datetime.now(tz).strftime("%Y-%m-%d")


def supabase_insert(table, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    r = requests.post(url, headers=headers, json=data)

    print(f"[SUPABASE] {table} {r.status_code} {r.text}")
    return r.status_code, r.text


def send_telegram(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})


# ---------------------------------------------------------
# GPT parse
# ---------------------------------------------------------

def parse_message(text):
    print("[RAW USER TEXT]", text)

    try:
        response = client.responses.create(
            prompt={"id": GPT_PROMPT_ID, "version": "1"},
            input=[{"role": "user", "content": text}],
            max_output_tokens=2048
        )
    except Exception as e:
        print("[GPT ERROR]", e)
        return None

    # Extract final message
    try:
        msg = response.output[0].content[0].text
        print("[GPT RAW]", msg)
        parsed = json.loads(msg)
        print("[GPT JSON]", parsed)
        return parsed
    except Exception as e:
        print("[PARSE FAIL]", e)
        return None


# ---------------------------------------------------------
# Webhook
# ---------------------------------------------------------

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()
    print("[TG UPDATE]", update)

    msg = update.get("message", {}).get("text", "")
    chat_id = update.get("message", {}).get("chat", {}).get("id")

    if not msg or not chat_id:
        return "ok", 200

    parsed = parse_message(msg)

    if not parsed:
        send_telegram(chat_id, "⚠️ Sorry, I couldn’t process that message.")
        return "ok", 200

    container = parsed.get("container")
    data = parsed.get("data")

    if container not in ["food", "sleep", "exercise"]:
        send_telegram(chat_id, "⚠️ Not sure what you’re trying to log.")
        return "ok", 200

    # Add universal fields
    data["chat_id"] = str(chat_id)
    data["user_id"] = str(chat_id)
    if "date" not in data or not data["date"]:
        data["date"] = lisbon_date()

    print(f"[FINAL DATA → {container}]:", data)

    status, body = supabase_insert(container, data)

    if str(status).startswith("2"):
        send_telegram(chat_id, parsed.get("reply_text", "Logged."))
    else:
        send_telegram(chat_id, f"❌ Could not log entry.\n{body}")

    return "ok", 200


@app.route("/")
def home():
    return "OK", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
