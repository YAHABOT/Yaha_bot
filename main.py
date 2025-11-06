#!/usr/bin/env python3
import os, json, logging, requests, base64, re, uuid, functools, time
from datetime import datetime, timezone
from flask import Flask, request, jsonify
import openai
from pydub import AudioSegment
import speech_recognition as sr

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("yaha_bot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY")
SUPABASE_URL       = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY  = os.getenv("SUPABASE_ANON_KEY")
GPT_PROMPT_ID      = os.getenv("GPT_PROMPT_ID")

app = Flask(__name__)
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# -------------------------------------------------------
# GPT HANDSHAKE runs immediately on import (once per worker)
# -------------------------------------------------------
def gpt_handshake_test():
    logger.info("🧠 Starting GPT handshake test...")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        if not GPT_PROMPT_ID:
            logger.warning("⚠️ GPT_PROMPT_ID missing.")
            return

        logger.info("Sending ping to GPT prompt ID: %s", GPT_PROMPT_ID)
        resp = client.responses.create(
            prompt={"id": GPT_PROMPT_ID, "version": "1"},
            input="Ping from Render — confirm connection alive."
        )
        output_text = getattr(resp, "output_text", None) or str(resp)
        logger.info("✅ GPT handshake success — Response:\n%s", output_text)
    except Exception as e:
        logger.error("❌ GPT handshake failed: %s", e, exc_info=True)

# Trigger it right now, once, when the worker boots
try:
    gpt_handshake_test()
except Exception as e:
    logger.error("GPT handshake could not start: %s", e)

# -------------------------------------------------------
# UTILITIES + REST identical to before
# -------------------------------------------------------
def now_iso():
    return datetime.now(timezone.utc).isoformat()

def sb_headers():
    return {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

SCHEMA = {
    "sleep": {"sleep_score": "float", "energy_score": "float", "duration_hr": "float", "resting_hr": "float", "notes": "string"},
    "food": {"meal_name": "string", "calories": "float", "protein_g": "float", "carbs_g": "float", "fat_g": "float", "fiber_g": "float", "notes": "string"},
    "exercise": {"workout_name": "string", "distance_km": "float", "duration_min": "float", "calories_burned": "float", "training_intensity": "float", "avg_hr": "float", "notes": "string"}
}

def fetch_table_columns(table):
    return list(SCHEMA.get(table, {}).keys())

def sanitize_payload(payload, table):
    valid = set(fetch_table_columns(table))
    return {k: v for k, v in payload.items() if k in valid and v not in (None, "", "null")}

def sb_post(table, payload):
    try:
        url = f"{SUPABASE_URL}/rest/v1/{table}"
        logger.info("INFO:yaha_bot:POST → %s", url)
        logger.info("Payload: %s", json.dumps(payload))
        r = requests.post(url, headers=sb_headers(), json=payload, timeout=15)
        if r.status_code not in (200, 201):
            logger.error("ERROR: Supabase POST %s — %s", r.status_code, r.text)
            return False
        logger.info("Supabase response: %s", r.text)
        return True
    except Exception as e:
        logger.error("Supabase POST exception: %s", e)
        return False

# -------------------------------------------------------
# TELEGRAM OCR & PARSING
# -------------------------------------------------------
def extract_text_from_image(file_url):
    try:
        img = requests.get(file_url, timeout=20).content
        b64 = base64.b64encode(img).decode("ascii")
        msgs = [
            {"role": "system", "content": "Extract visible text only, no commentary."},
            {"role": "user", "content": [
                {"type": "text", "text": "Extract all readable text clearly."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
            ]}
        ]
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        res = client.chat.completions.create(model="gpt-4o-mini", messages=msgs, max_tokens=1500)
        return res.choices[0].message.content.strip()
    except Exception as e:
        logger.error("OCR error: %s", e)
        return f"[OCR error] {e}"

def call_openai_for_json(user_text):
    schema_str = json.dumps(SCHEMA, indent=2)
    sys_prompt = (
        "You are a structured data extractor for a health tracking assistant.\n"
        "Recognize and return JSON only for these containers: sleep, food, exercise.\n"
        f"Use this schema:\n{schema_str}\n"
        "Return JSON list only. Example:\n"
        "[{'container':'sleep','fields':{'sleep_score':88.3},'notes':'summary'}]"
    )

    msgs = [{"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_text}]

    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        res = client.chat.completions.create(model="gpt-4o-mini", messages=msgs, max_tokens=900)
        text = res.choices[0].message.content.strip()
        parsed = json.loads(text)
    except Exception as e:
        logger.warning("AI parse failed: %s", e)
        return str(e), None

    if isinstance(parsed, dict):
        parsed = [parsed]
    cleaned = []
    for obj in parsed:
        c = obj.get("container")
        if c not in SCHEMA:
            continue
        fields = {}
        for key in SCHEMA[c].keys():
            if key in obj.get("fields", {}):
                val = obj["fields"][key]
                if isinstance(val, (int, float, str)):
                    fields[key] = val
        if fields:
            cleaned.append({"container": c, "fields": fields, "notes": obj.get("notes", "")})
    return json.dumps(cleaned), cleaned

# -------------------------------------------------------
# ROUTES
# -------------------------------------------------------
@app.route("/")
def index():
    return jsonify({"status": "ok"})

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True, silent=True)
        msg = data.get("message") or data.get("edited_message") or {}
        chat_id = msg.get("chat", {}).get("id")
        text = msg.get("text", "")

        ai_text, parsed_json = call_openai_for_json(text)
        results = []
        if parsed_json:
            for obj in parsed_json:
                c = obj["container"]
                payload = obj["fields"]
                payload["date"] = datetime.now().strftime("%Y-%m-%d")
                payload["created_at"] = now_iso()
                payload["recorded_at"] = now_iso()
                payload["user_id"] = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(chat_id)))
                ok = sb_post(c, payload)
                results.append((ok, f"{c}:{'ok' if ok else 'failed'}"))

        summary = f"OCR/Transcript preview:\n{text[:400]}\n\nProcessed.\n"
        if not parsed_json:
            summary += "⚠️ Parsing failed — no valid data found.\n"
        for ok, label in results:
            summary += f"✅ {label}\n" if ok else f"⚠️ {label}\n"
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={"chat_id": chat_id, "text": summary})
        return jsonify({"ok": True})
    except Exception as e:
        logger.error("Webhook error: %s", e, exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500
