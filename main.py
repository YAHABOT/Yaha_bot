#!/usr/bin/env python3
import os, json, logging, requests, base64, re, uuid, functools
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
# Utility functions
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
# Schema (validated fields for each container)
# -------------------------------------------------------
SCHEMA = {
    "sleep": {
        "sleep_score": float,
        "energy_score": float,
        "duration_hr": float,
        "resting_hr": float,
        "notes": str
    },
    "food": {
        "meal_name": str,
        "calories": float,
        "protein_g": float,
        "carbs_g": float,
        "fat_g": float,
        "fiber_g": float,
        "notes": str
    },
    "exercise": {
        "workout_name": str,
        "distance_km": float,
        "duration_min": float,
        "calories_burned": float,
        "training_intensity": float,
        "avg_hr": float,
        "notes": str
    }
}

@functools.lru_cache(maxsize=64)
def fetch_table_columns(table: str):
    return list(SCHEMA.get(table, {}).keys())

def sanitize_payload(payload, table):
    valid = set(fetch_table_columns(table))
    return {k: v for k, v in payload.items() if k in valid and v not in (None, "", "null")}

def sb_post(path, payload):
    try:
        r = requests.post(f"{SUPABASE_URL}{path}", headers=sb_headers(), json=payload, timeout=15)
        if r.status_code not in (200, 201):
            logger.error("Supabase POST error %s: %s", r.status_code, r.text)
            return False
        return True
    except Exception as e:
        logger.error("Supabase POST exception: %s", e)
        return False

# -------------------------------------------------------
# OCR + Voice
# -------------------------------------------------------
def extract_text_from_image(file_url: str):
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
        if openai_client:
            res = openai_client.chat.completions.create(model="gpt-4o-mini", messages=msgs, max_tokens=1500)
            return res.choices[0].message.content.strip()
        res = openai.ChatCompletion.create(model="gpt-4o-mini", messages=msgs, max_tokens=1500)
        return res.choices[0].message["content"].strip()
    except Exception as e:
        logger.error("OCR error: %s", e)
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
        logger.error("Voice transcription failed: %s", e)
        return f"[Voice error] {e}"

# -------------------------------------------------------
# AI JSON extractor
# -------------------------------------------------------
def call_openai_for_json(user_text):
    sys_prompt = (
        "You are a structured data extractor for a health tracking assistant.\n"
        "Recognize and return JSON only for these containers: sleep, food, exercise.\n"
        "Use the schema below:\n"
        f"{json.dumps(SCHEMA, indent=2)}\n"
        "Return a JSON list, example:\n"
        "[{'container':'sleep','fields':{'sleep_score':88.3,'duration_hr':7.2},'notes':'summary'}]"
    )

    msgs = [{"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_text}]

    try:
        if openai_client:
            res = openai_client.chat.completions.create(model="gpt-4o-mini", messages=msgs, max_tokens=900)
            text = res.choices[0].message.content.strip()
        else:
            res = openai.ChatCompletion.create(model="gpt-4o-mini", messages=msgs, max_tokens=900)
            text = res.choices[0].message["content"].strip()
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
        for key, val_type in SCHEMA[c].items():
            if key in obj.get("fields", {}):
                try:
                    if val_type == float:
                        fields[key] = clean_number(obj["fields"][key])
                    elif val_type == str:
                        fields[key] = str(obj["fields"][key])
                except Exception:
                    continue
        if fields:
            cleaned.append({"container": c, "fields": fields, "notes": obj.get("notes", "")})
    return json.dumps(cleaned), cleaned

# -------------------------------------------------------
# Data routing + mapping
# -------------------------------------------------------
def map_payload(container, fields, chat_id):
    uid = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(chat_id)))
    date_val = datetime.now().strftime("%Y-%m-%d")
    base = {
        "user_id": uid,
        "date": date_val,
        "created_at": now_iso(),
        "recorded_at": now_iso()
    }
    base.update(fields)
    return container, base

def route_to_container(parsed_json, chat_id):
    if not parsed_json:
        return [(False, "no_data")]
    results = []
    for obj in parsed_json:
        c = obj.get("container")
        fields = obj.get("fields", {})
        table, payload = map_payload(c, fields, chat_id)
        sanitized = sanitize_payload(payload, table)
        if not sanitized:
            results.append((False, f"{c}:empty_payload"))
            continue
        ok = sb_post(f"/rest/v1/{table}", sanitized)
        results.append((ok, f"{c}:ok" if ok else f"{c}:insert_failed"))
    return results

# -------------------------------------------------------
# Telegram + Flask
# -------------------------------------------------------
def send_telegram_message(chat_id, text):
    try:
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as e:
        logger.error("Telegram send error: %s", e)

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
    results = route_to_container(parsed_json, chat_id)

    summary = f"OCR/Transcript preview:\n{text[:400]}\n\nProcessed.\n"
    if not parsed_json:
        summary += "⚠️ Parsing failed — no valid data found.\n"
    for ok, label in results:
        summary += f"✅ {label}\n" if ok else f"⚠️ {label}\n"

    send_telegram_message(chat_id, summary)
    return jsonify({"ok": True})

# -------------------------------------------------------
# Run
# -------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))