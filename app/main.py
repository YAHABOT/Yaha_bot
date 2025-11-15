import os
import re
import json
import logging
import requests
from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# === ENV VARS ===
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_API_KEY = os.environ.get("SUPABASE_ANON_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# === HELPERS ===

def parse_food_message(text: str):
    """
    Example input:
    food: Choco Protein Pudding — 238 kcal | P 22.4 | C 15.3 | F 9.1
    """
    try:
        match = re.search(r'(?P<meal>.+?)\s*[-–—]\s*(?P<cal>\d+)\s*kcal.*?P\s*(?P<protein>[\d.]+).*?C\s*(?P<carbs>[\d.]+).*?F\s*(?P<fat>[\d.]+)', text, re.IGNORECASE)
        if match:
            return {
                "meal_name": match.group("meal").strip(),
                "calories": float(match.group("cal")),
                "protein_g": float(match.group("protein")),
                "carbs_g": float(match.group("carbs")),
                "fat_g": float(match.group("fat")),
            }
    except Exception as e:
        logging.error(f"Parse error: {e}")
    return None


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
        logging.warning("⚠️ TELEGRAM_BOT_TOKEN missing — cannot send message.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    logging.info(f"🌍 Telegram → {payload}")
    try:
        r = requests.post(url, json=payload)
        logging.info(f"📩 Telegram response: {r.status_code} {r.text}")
    except Exception as e:
        logging.error(f"💥 Telegram send failed: {e}")


# === WEBHOOK ===

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_text = message.get("text", "").strip()

    user_uuid = "68e5fa46-f6e3-5e14-8bdc-f2d549013c1f"
    logging.info(f"💬 Telegram chat_id={chat_id} mapped to UUID={user_uuid}")
    logging.info(f"🧠 User message: {user_text}")

    # Parse the food entry
    parsed = parse_food_message(user_text)

    if not parsed:
        send_telegram_message(chat_id, "⚠️ Couldn't read meal format. Try: `food: Meal Name — 500 kcal | P 30 | C 60 | F 10`")
        return jsonify({"status": "invalid_format"}), 200

    payload = {
        **parsed,
        "fiber_g": None,
        "notes": f"Added via Telegram on {datetime.utcnow().isoformat()}",
        "user_id": user_uuid,
        "created_at": datetime.utcnow().isoformat(),
        "recorded_at": datetime.utcnow().isoformat(),
        "date": datetime.utcnow().date().isoformat()
    }

    # Send to Supabase
    response = insert_record("food", payload)

    if response.status_code in [200, 201]:
        send_telegram_message(chat_id, f"✅ Logged: {parsed['meal_name']} ({parsed['calories']} kcal | P {parsed['protein_g']} | C {parsed['carbs_g']} | F {parsed['fat_g']})")
    else:
        send_telegram_message(chat_id, f"⚠️ Failed to log entry ({response.status_code})")

    return jsonify({"status": "ok"}), 200


@app.route("/", methods=["GET"])
def home():
    return "YAHA bot online and tracking meals.", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
