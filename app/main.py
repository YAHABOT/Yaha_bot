import os
from flask import Flask, request
from openai import OpenAI
import requests
import json
from datetime import datetime
import pytz

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

# -------------------------------
# Telegram helpers
# -------------------------------
def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    requests.post(url, json=payload)


# -------------------------------
# GPT PARSER
# -------------------------------
def call_gpt_parser(prompt: str):
    try:
        response = openai_client.responses.parse(
            model="gpt-4.1-mini",
            input=prompt
        )
        return response.output

    except Exception as e:
        print("GPT PARSE ERROR:", e)
        return None


# -------------------------------
# Date helper
# -------------------------------
def get_local_date():
    tz = pytz.timezone("Europe/Lisbon")
    return datetime.now(tz).strftime("%Y-%m-%d")


# -------------------------------
# Supabase insert helper
# -------------------------------
def supabase_insert(table, payload):
    url = f"{SUPABASE_URL}/rest/v1/{table}"

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

    res = requests.post(url, headers=headers, json=payload)

    try:
        body = res.json()
    except:
        body = res.text

    print("Supabase response status=", res.status_code, "body=", body)
    return res.status_code, body


# -------------------------------
# Webhook endpoint
# -------------------------------
@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    try:
        update = request.get_json()

        # --- FIX: sometimes Telegram sends a LIST of updates ---
        if isinstance(update, list):
            update = update[0]

        if not isinstance(update, dict):
            print("WEBHOOK ERROR: update not a dict:", update)
            return "ok", 200

        message = update.get("message") or update.get("edited_message")

        if not isinstance(message, dict):
            print("WEBHOOK ERROR: message missing or not dict:", message)
            return "ok", 200

        chat = message.get("chat") or {}
        chat_id = chat.get("id")

        if not chat_id:
            print("WEBHOOK ERROR: no chat_id")
            return "ok", 200

        user_text = message.get("text", "").strip()

        if not user_text:
            send_telegram_message(chat_id, "⚠️ Empty message received.")
            return "ok", 200

        # Feed user text to GPT parser
        parsed = call_gpt_parser(user_text)

        if parsed is None:
            send_telegram_message(chat_id, "⚠️ Sorry, I couldn’t process that.")
            return "ok", 200

        # ------------------------------------------
        # If GPT returns plain text → send back
        # ------------------------------------------
        if isinstance(parsed, str):
            send_telegram_message(chat_id, parsed)
            return "ok", 200

        # ------------------------------------------
        # If GPT returns structured JSON
        # ------------------------------------------
        if isinstance(parsed, dict):
            container = parsed.get("container")
            data = parsed.get("data", {})
            msg = parsed.get("message_to_user", "Logged.")

            # Add chat_id and date if missing
            data["chat_id"] = str(chat_id)
            if not data.get("date"):
                data["date"] = get_local_date()

            # Insert into correct table
            if container in ["food", "sleep", "exercise"]:
                status, body = supabase_insert(container, data)

                if status >= 200 and status < 300:
                    send_telegram_message(chat_id, msg)
                else:
                    send_telegram_message(
                        chat_id,
                        f"{msg}\nHowever, saving to {container} failed:\n{body}"
                    )
                return "ok", 200

            # Unknown container
            send_telegram_message(chat_id, msg)
            return "ok", 200

        # Fallback
        send_telegram_message(chat_id, str(parsed))
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
