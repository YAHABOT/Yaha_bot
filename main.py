#!/usr/bin/env python3
import os, json, logging, requests, base64, re, uuid
from datetime import datetime, timezone
from flask import Flask, request, jsonify
import openai

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("yaha_bot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY")
SUPABASE_URL       = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY  = os.getenv("SUPABASE_ANON_KEY")
GPT_PROMPT_ID      = os.getenv("GPT_PROMPT_ID")

app = Flask(__name__)
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

def gpt_handshake_test():
    logger.info("🧠 Starting GPT handshake test...")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.responses.create(
            prompt={"id": GPT_PROMPT_ID, "version": "1"},
            input="Ping from Render — confirm connection alive."
        )
        text = getattr(resp, "output_text", None) or str(resp)
        logger.info("✅ GPT handshake success — %s", text[:120])
    except Exception as e:
        logger.error("❌ GPT handshake failed: %s", e, exc_info=True)

try:
    gpt_handshake_test()
except Exception as e:
    logger.error("Handshake test failed: %s", e)

def sb_headers():
    return {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

def sb_post(table, payload):
    try:
        # Debug logging of exact URL
        full_url = f"{SUPABASE_URL}/rest/v1/{table}" if not SUPABASE_URL.endswith("/rest/v1") else f"{SUPABASE_URL}/{table}"
        logger.info("🧩 ENV SUPABASE_URL: %s", SUPABASE_URL)
        logger.info("🧩 Final POST URL: %s", full_url)
        logger.info("🧩 Payload: %s", json.dumps(payload))

        r = requests.post(full_url, headers=sb_headers(), json=payload, timeout=15)
        logger.info("🔁 Response %s: %s", r.status_code, r.text)
        return r.status_code in (200, 201)
    except Exception as e:
        logger.error("Supabase POST exception: %s", e, exc_info=True)
        return False

@app.route("/")
def index():
    return jsonify({"status": "ok"})

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True, silent=True)
        msg = data.get("message") or {}
        chat_id = msg.get("chat", {}).get("id", "unknown")
        text = msg.get("text", "unknown input")

        payload = {
            "meal_name": "Debug Insert",
            "calories": 111,
            "protein_g": 11,
            "carbs_g": 11,
            "fat_g": 11,
            "fiber_g": 1,
            "notes": f"Auto test at {datetime.now(timezone.utc).isoformat()}",
            "user_id": str(chat_id),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "recorded_at": datetime.now(timezone.utc).isoformat()
        }

        sb_post("food", payload)
        return jsonify({"ok": True})
    except Exception as e:
        logger.error("Webhook error: %s", e)
        return jsonify({"error": str(e)}), 500
