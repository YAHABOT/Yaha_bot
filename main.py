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
# Utility helpers
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
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return val
    try:
        cleaned = re.findall(r"[-+]?\d*\.\d+|\d+", str(val))
        return float(cleaned[0]) if cleaned else None
    except Exception:
        return None

def fetch_table_columns(table):
    """Fetch column list from Supabase's REST /columns endpoint"""
    try:
        url = f"{SUPABASE_URL}/rest/v1/{table}?limit=1"
        headers = sb_headers()
        headers["Range"] = "0-0"
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code in (200, 206):
            cols = r.headers.get("content-range")
            # fallback: query PostgREST /rpc if needed
        # Plan B: use schema cache via /rpc if available
        meta = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=headers, params={"limit": 1})
        if meta.ok:
            return list(meta.json()[0].keys())
    except Exception as e:
        logger.warning("Could not fetch schema: %s", e)
    return []

def sanitize_payload(payload, table):
    """Drop any keys not existing in table schema"""
    valid = set(fetch_table_columns(table))
    return {k: v for k, v in payload.items() if k in valid}

def sb_post(path, payload):
    url = f"{SUPABASE_URL}{path}"
    r = requests.post(url, headers=sb_headers(), json=payload, timeout=15)
    if r.status_code not in (200, 201):
        logger.error("Supabase POST %s: %s\nPayload: %s", r.status_code, r.text, json.dumps(payload))
        return False
    return True

# -------------------------------------------------------
# OCR
# -------------------------------------------------------
def extract_text_from_image(file_url: str) -> str:
    try:
        resp = requests.get(file_url, timeout=20)
        resp.raise_for_status()
        b64_image = base64.b64encode(resp.content).decode("ascii")

        msgs = [
            {"role": "system", "content": "Extract visible text, no commentary."},
            {"role": "user", "content": [
                {"type": "text", "text": "Extract all readable text."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}}
            ]}
        ]

        if openai_client:
            comp = openai_client.chat.completions.create(model="gpt-4o-mini", messages=msgs, max_tokens=1200)
            return comp.choices[0].message.content.strip()
        else:
            comp = openai.ChatCompletion.create(model="gpt-4o-mini", messages=msgs, max_tokens=1200)
            return comp.choices[0].message["content"].strip()
    except Exception as e:
        logger.exception("OCR error")
        return f"[OCR error] {e}"

# -------------------------------------------------------
# Voice
# -------------------------------------------------------
def transcribe_voice(file_url):
    try:
        ogg = requests.get(file_url, timeout=30).content
        tmp_ogg, tmp_wav = "/tmp/voice.ogg", "/tmp/voice.wav"
        with open(tmp_ogg, "wb") as f: f.write(ogg)
        AudioSegment.from_ogg(tmp_ogg).export(tmp_wav, format="wav")
        rec = sr.Recognizer()
        with sr.AudioFile(tmp_wav) as src:
            return rec.recognize_google(rec.record(src))
    except Exception as e:
        logger.exception("Voice transcription failed")
        return f"[Voice error] {e}"

# -------------------------------------------------------
# JSON generation
# -------------------------------------------------------
def call_openai_for_json(user_text):
    system_prompt = (
        "You are a JSON generator for a health tracking assistant. "
        "Return ONLY valid JSON with keys: "
        "'container' (sleep|exercise|food|user), 'fields' (object), and 'notes' (string). "
        "Output pure JSON, no text around it."
    )
    msgs = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]
    try:
        if openai_client:
            resp = openai_client.chat.completions.create(model="gpt-4o-mini", messages=msgs, max_tokens=400)
            ai_text = resp.choices[0].message.content.strip()
        else:
            resp = openai.ChatCompletion.create(model="gpt-4o-mini", messages=msgs, max_tokens=400)
            ai_text = resp.choices[0].message["content"].strip()
        parsed = json.loads(ai_text)
        return ai_text, parsed if isinstance(parsed, dict) else None
    except Exception as e:
        logger.warning("Bad AI response: %s", e)
        return str(e), None

# -------------------------------------------------------
# Mapping
# -------------------------------------------------------
def map_payload(container, fields, chat_id):
    ts = now_iso()
    user_id_str = str(chat_id)
    date_val = fields.get("date") or ts[:10]

    if container == "sleep":
        return "sleep", {
            "user_id": user_id_str,
            "date": date_val,
            "sleep_score": clean_number(fields.get("sleep_score")),
            "energy_score": clean_number(fields.get("energy_score")),
            "duration_hr": clean_number(fields.get("duration_hr") or fields.get("duration")),
            "resting_hr": clean_number(fields.get("resting_hr")),
            "notes": fields.get("notes"),
        }
    if container == "exercise":
        return "exercise", {
            "user_id": user_id_str,
            "date": date_val,
            "workout_name": fields.get("workout_name") or "Workout",
            "distance_km": clean_number(fields.get("distance_km")),
            "duration_min": clean_number(fields.get("duration_min") or fields.get("duration")),
            "calories_burned": clean_number(fields.get("calories_burned") or fields.get("calories_kcal")),
        }
    if container == "food":
        return "food", {
            "user_id": user_id_str,
            "date": date_val,
            "meal_name": fields.get("meal_name") or fields.get("name"),
            "calories_kcal": clean_number(fields.get("calories_kcal")),
            "protein_g": clean_number(fields.get("protein_g")),
            "carbs_g": clean_number(fields.get("carbs_g")),
            "fat_g": clean_number(fields.get("fat_g")),
            "notes": fields.get("notes"),
        }
    return None, None

# -------------------------------------------------------
# Router
# -------------------------------------------------------
def route_to_container(parsed_json, chat_id):
    if not parsed_json or "container" not in parsed_json:
        return False, "no_container"
    container = parsed_json["container"]
    fields = parsed_json.get("fields", {}) or {}
    table, payload = map_payload(container, fields, chat_id)
    if not table:
        return False, "unknown_container"

    sanitized = sanitize_payload(payload, table)
    if not sanitized:
        return False, "empty_payload"

    ok = sb_post(f"/rest/v1/{table}", sanitized)
    return ok, "insert_ok" if ok else "insert_failed"

# -------------------------------------------------------
# Logging + Telegram
# -------------------------------------------------------
def log_entry(chat_id, text, ai_text, parsed_json, status):
    sb_post("/rest/v1/entries", {
        "chat_id": str(chat_id),
        "user_message": text,
        "ai_response": ai_text,
        "parsed": bool(parsed_json),
        "parsed_json": parsed_json,
        "created_at": now_iso(),
        "notes": status,
    })

def send_telegram_message(chat_id, text):
    try:
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception:
        logger.exception("Telegram send failed")

# -------------------------------------------------------
# Flask
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

    if "photo" in msg:
        fid = msg["photo"][-1]["file_id"]
        fpath = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={fid}", timeout=10).json().get("result", {}).get("file_path")
        text = extract_text_from_image(f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{fpath}") if fpath else "[OCR error]"
    elif "voice" in msg:
        fid = msg["voice"]["file_id"]
        fpath = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={fid}", timeout=10).json().get("result", {}).get("file_path")
        text = transcribe_voice(f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{fpath}") if fpath else "[Voice error]"
    else:
        text = msg.get("text", "")

    ai_text, parsed_json = call_openai_for_json(text)
    ok, status = route_to_container(parsed_json, chat_id)
    log_entry(chat_id, text, ai_text, parsed_json, status)

    preview = (text[:400] + "…") if len(text) > 400 else text
    msg_txt = f"OCR/Transcript preview:\n{preview}\n\nProcessed.\n"
    msg_txt += "✅ Saved." if ok else f"⚠️ Log only — {status}."
    if parsed_json and parsed_json.get("notes"):
        msg_txt += f"\nNotes: {parsed_json['notes']}"

    send_telegram_message(chat_id, msg_txt)
    return jsonify({"ok": True})

# -------------------------------------------------------
# Run
# -------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
