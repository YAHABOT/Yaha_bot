#!/usr/bin/env python3
import os, json, logging, requests, base64, re, functools
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
# Helpers
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
        n = re.findall(r"[-+]?\d*\.\d+|\d+", str(val))
        return float(n[0]) if n else None
    except Exception:
        return None

# -------------------------------------------------------
# Static schema definitions (so sanitizer doesn’t blank)
# -------------------------------------------------------
SCHEMA_OVERRIDES = {
    "sleep": {"user_id","date","sleep_score","energy_score","duration_hr","resting_hr","notes","created_at","recorded_at"},
    "food": {"user_id","date","meal_name","calories","protein_g","carbs_g","fat_g","fiber_g","notes","created_at","recorded_at"},
    "exercise": {"user_id","date","workout_name","distance_km","duration_min","calories_burned","training_intensity","avg_hr","notes","created_at","recorded_at"},
    "weight_history": {"user_id","weight_kg","recorded_at"},
    "foodbank": {"user_id","name","calories","protein_g","carbs_g","fat_g","fiber_g","notes","created_at"},
    "containers": {"user_id","name","created_at"},
    "users": {"telegram_id","full_name"}
}

@functools.lru_cache(maxsize=64)
def fetch_table_columns(table: str):
    return list(SCHEMA_OVERRIDES.get(table, []))

def sanitize_payload(payload, table):
    valid = set(fetch_table_columns(table))
    return {k: v for k, v in payload.items() if k in valid and v not in (None, "", "null")}

def sb_post(path, payload):
    try:
        r = requests.post(f"{SUPABASE_URL}{path}", headers=sb_headers(), json=payload, timeout=15)
        if r.status_code not in (200, 201):
            logger.error("Supabase insert failed %s %s", r.status_code, r.text)
            return False
        return True
    except Exception as e:
        logger.error("Supabase POST error: %s", e)
        return False

# -------------------------------------------------------
# OCR + Voice
# -------------------------------------------------------
def extract_text_from_image(file_url: str):
    try:
        img = requests.get(file_url, timeout=20).content
        b64 = base64.b64encode(img).decode("ascii")
        msgs = [
            {"role": "system", "content": "Extract only readable text. No commentary."},
            {"role": "user", "content": [
                {"type": "text", "text": "Extract text clearly and preserve layout."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
            ]}
        ]
        if openai_client:
            res = openai_client.chat.completions.create(model="gpt-4o-mini", messages=msgs, max_tokens=1500)
            return res.choices[0].message.content.strip()
        res = openai.ChatCompletion.create(model="gpt-4o-mini", messages=msgs, max_tokens=1500)
        return res.choices[0].message["content"].strip()
    except Exception as e:
        return f"[OCR error] {e}"

def transcribe_voice(file_url):
    try:
        data = requests.get(file_url, timeout=30).content
        ogg, wav = "/tmp/v.ogg", "/tmp/v.wav"
        with open(ogg, "wb") as f: f.write(data)
        AudioSegment.from_ogg(ogg).export(wav, format="wav")
        r = sr.Recognizer()
        with sr.AudioFile(wav) as src:
            return r.recognize_google(r.record(src))
    except Exception as e:
        return f"[Voice error] {e}"

# -------------------------------------------------------
# JSON generator (field filtering logic)
# -------------------------------------------------------
def call_openai_for_json(user_text):
    sys_prompt = (
        "You are a JSON generator for a health tracker. "
        "Only extract fields that match one of the known containers: sleep, food, exercise, user. "
        "Ignore unrelated text. Return valid JSON with keys: "
        "'container', 'fields', 'notes'. Output JSON only."
    )
    msgs = [{"role":"system","content":sys_prompt},{"role":"user","content":user_text}]
    try:
        if openai_client:
            res = openai_client.chat.completions.create(model="gpt-4o-mini", messages=msgs, max_tokens=400)
            text = res.choices[0].message.content.strip()
        else:
            res = openai.ChatCompletion.create(model="gpt-4o-mini", messages=msgs, max_tokens=400)
            text = res.choices[0].message["content"].strip()
        parsed = json.loads(text)
        return text, parsed if isinstance(parsed, dict) else None
    except Exception as e:
        logger.warning("AI parse fail: %s", e)
        return str(e), None

# -------------------------------------------------------
# Mapping to Supabase payloads
# -------------------------------------------------------
def map_payload(container, fields, chat_id):
    uid = str(chat_id)
    date_val = fields.get("date") or datetime.now().strftime("%Y-%m-%d")

    if container == "sleep":
        return "sleep", {
            "user_id": uid,
            "date": date_val,
            "sleep_score": clean_number(fields.get("sleep_score")),
            "energy_score": clean_number(fields.get("energy_score")),
            "duration_hr": clean_number(fields.get("duration_hr")),
            "resting_hr": clean_number(fields.get("resting_hr")),
            "notes": fields.get("notes"),
            "created_at": now_iso(),
            "recorded_at": now_iso()
        }

    if container == "food":
        return "food", {
            "user_id": uid,
            "date": date_val,
            "meal_name": fields.get("meal_name") or "Meal",
            "calories": clean_number(fields.get("calories")),
            "protein_g": clean_number(fields.get("protein_g")),
            "carbs_g": clean_number(fields.get("carbs_g")),
            "fat_g": clean_number(fields.get("fat_g")),
            "fiber_g": clean_number(fields.get("fiber_g")),
            "notes": fields.get("notes"),
            "created_at": now_iso(),
            "recorded_at": now_iso()
        }

    if container == "exercise":
        return "exercise", {
            "user_id": uid,
            "date": date_val,
            "workout_name": fields.get("workout_name") or "Workout",
            "distance_km": clean_number(fields.get("distance_km")),
            "duration_min": clean_number(fields.get("duration_min")),
            "calories_burned": clean_number(fields.get("calories_burned")),
            "training_intensity": clean_number(fields.get("training_intensity")),
            "avg_hr": clean_number(fields.get("avg_hr")),
            "notes": fields.get("notes"),
            "created_at": now_iso(),
            "recorded_at": now_iso()
        }

    return None, None

# -------------------------------------------------------
# Router + logger
# -------------------------------------------------------
def route_to_container(parsed_json, chat_id):
    if not parsed_json or "container" not in parsed_json:
        return False, "no_container"
    c = parsed_json["container"]
    fields = parsed_json.get("fields", {}) or {}
    table, payload = map_payload(c, fields, chat_id)
    if not table:
        return False, "unknown_container"
    sanitized = sanitize_payload(payload, table)
    if not sanitized:
        return False, "empty_payload"
    ok = sb_post(f"/rest/v1/{table}", sanitized)
    return ok, "insert_ok" if ok else "insert_failed"

def log_entry(chat_id, text, ai_text, parsed_json, status):
    sb_post("/rest/v1/entries", {
        "chat_id": str(chat_id),
        "user_message": text,
        "ai_response": ai_text,
        "parsed": bool(parsed_json),
        "parsed_json": parsed_json,
        "created_at": now_iso(),
        "notes": status
    })

def send_telegram_message(chat_id, text):
    try:
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as e:
        logger.error("Telegram send fail: %s", e)

# -------------------------------------------------------
# Flask app
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
    msg_txt += "✅ Logged successfully." if ok else f"⚠️ Insert failed: {status}."
    if parsed_json and parsed_json.get("notes"):
        msg_txt += f"\nNotes: {parsed_json['notes']}"
    send_telegram_message(chat_id, msg_txt)
    return jsonify({"ok": True})

# -------------------------------------------------------
# Run
# -------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))