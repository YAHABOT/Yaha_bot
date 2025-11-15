import os
from flask import Flask, request
from openai import OpenAI
import requests
import json

app = Flask(__name__)

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
# GPT PARSER (FIXED FOR v2)
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
# Webhook endpoint
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

        # Feed user text to GPT parser
        parsed = call_gpt_parser(user_text)

        if parsed is None:
            send_telegram_message(chat_id, "⚠️ Sorry, I couldn’t process that.")
            return "ok", 200

        # If parser returns plain text → send as-is
        if isinstance(parsed, str):
            send_telegram_message(chat_id, parsed)
            return "ok", 200

        # If parser returns JSON → pretty print it
        if isinstance(parsed, dict):
            send_telegram_message(chat_id, json.dumps(parsed, indent=2))
            return "ok", 200

        # fallback
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
