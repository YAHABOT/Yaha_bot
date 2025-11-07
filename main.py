import os
import json
import logging
import requests
from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s:%(message)s")

# === ENV VARIABLES ===
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_API_KEY = os.environ.get("SUPABASE_ANON_KEY")
GPT_PROMPT_ID = os.environ.get("GPT_PROMPT_ID")

# === SETUP CHECK ===
@app.before_first_request
def startup_check():
    logging.info("🧠 Starting GPT handshake test...")
    if not GPT_PROMPT_ID:
        logging.warning("⚠️ No GPT_PROMPT_ID found — skipping handshake test.")
        return
    try:
        resp = requests.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY')}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4.1",
                "input": f"Hello from Render — GPT handshake test for prompt ID {GPT_PROMPT_ID}"
            }
        )
        if resp.status_code == 200:
            logging.info("✅ GPT handshake success — Connection confirmed. I am active and ready to assist.")
        else:
            logging.warning(f"⚠️ GPT handshake failed: {resp.status_code} {resp.text}")
    except Exception as e:
        logging.error(f"❌ GPT handshake exception: {e}")

# === SUPABASE INSERT FUNCTION ===
def insert_record(table_name, payload):
    url = f"{SUPABASE_URL}/{table_name}"
    headers = {
        "apikey": SUPABASE_API_KEY,
        "Authorization": f"Bearer {SUPABASE_API_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

    logging.info(f"🧩 ENV SUPABASE_URL: {SUPABASE_URL}")
    logging.info(f"🧩 Final POST URL: {url}")
    logging.info(f"🧩 Payload: {json.dumps(payload)}")

    response = requests.post(url, headers=headers, json=payload)
    logging.info(f"🧩 Response {response.status_code}: {response.text}")
    return response


# === TELEGRAM WEBHOOK ===
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    chat_id = data.get("message", {}).get("chat", {}).get("id", "unknown")
    text = data.get("message", {}).get("text", "unknown")

    # Mock user mapping (you can replace this later with DB lookup)
    user_uuid = "68e5fa46-f6e3-5e14-8bdc-f2d549013c1f"
    logging.info(f"💬 Telegram chat_id={chat_id} mapped to UUID={user_uuid}")

    # Debug payload (you’ll replace this with OCR/GPT result later)
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

    # ✅ Always return something to Telegram to prevent silence
    if response.status_code in [200, 201]:
        return jsonify({"status": "ok", "message": "Food entry logged successfully"}), 200
    else:
        return jsonify({
            "status": "error",
            "message": f"Insert failed: {response.status_code}",
            "details": response.text
        }), 200


# === HEALTH CHECK ===
@app.route("/", methods=["GET"])
def home():
    return "YAHA bot is live and running!", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
