import os
import json
import logging
import requests
from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s:%(message)s")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_API_KEY = os.environ.get("SUPABASE_ANON_KEY")
GPT_PROMPT_ID = os.environ.get("GPT_PROMPT_ID")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

def insert_record(table_name, payload):
    url = f"{SUPABASE_URL}/{table_name}"
    headers = {
        "apikey": SUPABASE_API_KEY,
        "Authorization": f"Bearer {SUPABASE_API_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    response = requests.post(url, headers=headers, json=payload)
    logging.info(f"🧩 Supabase POST {response.status_code}: {response.text}")
    return response

def send_telegram_message(chat_id, text):
    if not TELEGRAM_BOT_TOKEN:
        logging.warning("⚠️ No TELEGRAM_BOT_TOKEN in environment — cannot send message.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    r = requests.post(url, json=payload)
    logging.info(f"📩 Telegram sendMessage response: {r.status_code} {r.text}")

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_text = message.get("text", "")

    user_uuid = "68e5fa46-f6e3-5e14-8bdc-f2d549013c1f"
    logging.info(f"💬 Telegram chat_id={chat_id} mapped to UUID={user_uuid}")

    payload = {
        "meal_name": "Debug Insert",
        "calories": 111,
        "protein_g": 11,
        "carbs_g": 11,
        "fat_g": 11,
        "fiber_g": 1,
        "notes": f"Auto test at {datetime.utcnow().isoformat()}",
        "user_id": user_uuid,
        "created_at": datetime.utcnow().isoformat(),
        "recorded_at": datetime.utcnow().isoformat(),
        "date": datetime.utcnow().date().isoformat()
    }

    response = insert_record("food", payload)

    if response.status_code in [200, 201]:
        send_telegram_message(chat_id, "✅ Food entry logged successfully.")
    else:
        send_telegram_message(chat_id, f"⚠️ Failed to log entry — {response.status_code}.")

    return jsonify({"status": "ok"}), 200

@app.route("/", methods=["GET"])
def home():
    return "YAHA bot is live and running!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
