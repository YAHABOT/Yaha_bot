#!/usr/bin/env python3
import os, json, logging, requests, base64, re
from datetime import datetime, timezone
from flask import Flask, request, jsonify
import openai
from pydub import AudioSegment
import speech_recognition as sr

# -------------------------------------------------------
# Setup
# -------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("yaha_bot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY")
SUPABASE_URL       = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY  = os.getenv("SUPABASE_ANON_KEY")

openai_client = None
if OPENAI_API_KEY:
    try:
        from openai import OpenAI as OpenAIClient
        openai_client = OpenAIClient(api_key=OPENAI_API_KEY)
    except Exception:
        openai.api_key = OPENAI_API_KEY
        openai_client = None

app = Flask(__name__)
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# -------------------------------------------------------
# Utilities
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

def clean_number(val):
    if val is None: return None
    try:
        m = re.findall(r"[-+]?\d*\.\d+|\d+", str(val))
        return float(m[0]) if m else None
    except Exception:
        return None

# -------------------------------------------------------
# Supabase helpers
# -------------------------------------------------------
def get_or_create_user(telegram_id):
    """Return the user's UUID, creating if not exists."""
    url = f"{SUPABASE_URL}/rest/v1/users"
    headers = sb_headers()

    r = requests.get(url, headers=headers, params={"telegram_id": f"eq.{telegram_id}"})
    if r.ok and r.json():
        return r.json()[0]["id"]

    # create
    payload = {"telegram_id": str(telegram_id), "full_name": f"User_{telegram_id}"}
    r2 = requests.post(url, headers=headers, json=payload)
    if r2.ok and r2.json():
        return r2.json()[0]["id"]
    logger.error("User create failed: %s %s", r2.status_code, r2.text)
    return None

def sb_post(table, payload):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    r = requests.post(url, headers=sb_headers(), json=payload)
    if r.status_code not in (200, 201):
        logger.error("Insert failed: %s %s", r.status_code, r.text)
        return False
    return True

def log_entry(chat_id, text, ai_text, parsed_json, status):
    sb_post("entries", {
        "chat_id": str(chat_id),
        "user_message": text,
        "ai_response": ai_text,
        "parsed": bool(parsed_json),
        "parsed_json": parsed_json,
        "created_at": now_iso(),
        "notes": status,
    })

# -------------------------------------------------------
# OCR and Voice
# -------------------------------------------------------
def extract_text_from_image(file_url):
    try:
        img_bytes = requests.get(file_url, timeout=20).content
        b64_image = base64.b64encode(img_bytes).decode("ascii")
        msgs = [
            {"role": "system", "content": "Extract visible text, no commentary."},
            {"role": "user", "content": [
                {"type": "text", "text": "Extract all readable text."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}}
            ]}
        ]
        if openai_client:
            comp = openai_client.chat.completions.create(model="gpt-4o-mini", messages=msgs, max_tokens=1500)
            return comp.choices[0].message.content.strip()
        comp = openai.ChatCompletion.create(model="gpt-4o-mini", messages=msgs, max_tokens=1500)
        return comp.choices[0].message["content"].strip()
    except Exception as e:
        logger.exception("OCR error")
        return f"[OCR error] {e}"

def transcribe_voice(file_url):
    try:
        data = requests.get(file_url, timeout=30).content
        tmp_ogg, tmp_wav = "/tmp/voice.ogg", "/tmp/voice.wav"
        with open(tmp_ogg, "wb") as f: f.write(data)
        AudioSegment.from_ogg(tmp_ogg).export(tmp_wav, format="wav")
        rec = sr.Recognizer()
        with sr.AudioFile(tmp_wav) as src:
            return rec.recognize_google(rec.record(src))
    except Exception as e:
        logger.exception("Voice fail")
        return f"[Voice error] {e}"

# -------------------------------------------------------
# OpenAI JSON logic
# -------------------------------------------------------
CONTAINER_FIELDS = {
    "sleep": ["sleep_score", "energy_score", "duration_hr", "resting_hr", "notes"],
    "food": ["meal_name", "calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "notes"],
    "exercise": ["workout_name", "distance_km", "duration_min", "calories_burned", "training_intensity", "avg_hr", "notes"],
    "weight_history": ["weight_kg"],
}

def call_openai_for_json(user_text):
    system_prompt = (
        "You are a JSON generator for a health tracker. "
        "Return ONLY JSON with keys: container (sleep|exercise|food|weight_history), "
        "fields (object), and notes (string). "
        "Filter the text to only include fields relevant to that container."
    )
    msgs = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]
    try:
        if openai_client:
            r = openai_client.chat.completions.create(model="gpt-4o-mini", messages=msgs, max_tokens=600)
            t = r.choices[0].message.content.strip()
        else:
            r = openai.ChatCompletion.create(model="gpt-4o-mini", messages=msgs, max_tokens=600)
            t = r.choices[0].message["content"].strip()
        return t, json.loads(t)
    except Exception as e:
        logger.warning("Parse fail: %s", e)
        return str(e), None

# -------------------------------------------------------
# Insert router
# -------------------------------------------------------
def insert_container(container, fields, user_id):
    if container not in CONTAINER_FIELDS:
        return False, "no_container"
    payload = {"user_id": user_id, "date": now_iso()[:10], "created_at": now_iso(), "recorded_at": now_iso()}
    for f in CONTAINER_FIELDS[container]:
        if f in fields:
            payload[f] = fields[f]
    ok = sb_post(container, payload)
    return ok, "insert_ok" if ok else "insert_failed"

# -------------------------------------------------------
# Telegram send
# -------------------------------------------------------
def send_telegram(chat_id, text):
    try:
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception:
        logger.exception("Telegram send fail")

# -------------------------------------------------------
# Flask webhook
# -------------------------------------------------------
@app.route("/")
def index():
    return jsonify({"status": "ok"})

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True)
    msg = data.get("message") or data.get("edited_message") or {}
    chat_id = msg.get("chat", {}).get("id")
    text = ""

    # detect content type
    if "photo" in msg:
        fid = msg["photo"][-1]["file_id"]
        fp = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={fid}", timeout=10).json().get("result", {}).get("file_path")
        text = extract_text_from_image(f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{fp}") if fp else "[OCR error]"
    elif "voice" in msg:
        fid = msg["voice"]["file_id"]
        fp = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={fid}", timeout=10).json().get("result", {}).get("file_path")
        text = transcribe_voice(f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{fp}") if fp else "[Voice error]"
    else:
        text = msg.get("text", "")

    ai_text, parsed = call_openai_for_json(text)
    user_id = get_or_create_user(chat_id)

    ok, status = (False, "parse_failed")
    if parsed:
        ok, status = insert_container(parsed.get("container"), parsed.get("fields", {}), user_id)

    log_entry(chat_id, text, ai_text, parsed, status)

    msg_out = f"OCR/Transcript preview:\n{text[:400]}\n\nProcessed.\n"
    msg_out += "✅ Logged successfully." if ok else f"⚠️ Insert failed: {status}"
    if parsed and parsed.get("notes"):
        msg_out += f"\nNotes: {parsed['notes']}"
    send_telegram(chat_id, msg_out)
    return jsonify({"ok": True})

# -------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))