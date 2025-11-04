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
# Schema + Field Definitions
# -------------------------------------------------------
CONTAINER_FIELDS = {
    "sleep": ["sleep_score", "energy_score", "duration_hr", "resting_hr", "notes"],
    "food": ["meal_name", "calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "notes"],
    "exercise": ["workout_name", "distance_km", "duration_min", "calories_burned", "training_intensity", "avg_hr", "notes"],
}

SCHEMA_OVERRIDES = {
    "sleep": {"user_id","date","sleep_score","energy_score","duration_hr","resting_hr","notes","created_at","recorded_at"},
    "food": {"user_id","date","meal_name","calories","protein_g","carbs_g","fat_g","fiber_g","notes","created_at","recorded_at"},
    "exercise": {"user_id","date","workout_name","distance_km","duration_min","calories_burned","training_intensity","avg_hr","notes","created_at","recorded_at"},
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
            {"role": "system", "content": "Extract readable text, no commentary."},
            {"role": "user", "content": [
                {"type": "text", "text": "Extract all readable text."},
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
# OpenAI JSON generator
# -------------------------------------------------------
def call_openai_for_json(user_text):
    sys_prompt = (
        "You are a data parser for a health tracking app. "
        "You must detect which container(s) this message belongs to among: sleep, food, exercise. "
        "For each relevant container, only extract the following fields: "
        f"{json.dumps(CONTAINER_FIELDS)}. "
        "Ignore any unrelated text. Return JSON in the form:\n"
        "{'container':'sleep','fields':{...},'notes':'summary'}\n"
        "If multiple containers appear, return a list of such objects. Output pure JSON only."
    )

    msgs = [{"role":"system","content":sys_prompt},{"role":"user","content":user_text}]
    try:
        if openai_client:
            res = openai_client.chat.completions.create(model="gpt-4o-mini", messages=msgs, max_tokens=700)
            text = res.choices[0].message.content.strip()
        else:
            res = openai.ChatCompletion.create(model="gpt-4o-mini", messages=msgs, max_tokens=700)
            text = res.choices[0].message["content"].strip()
        parsed = json.loads(text)
        return text, parsed
    except Exception as e:
        logger.warning("AI JSON parse fail: %s", e)
        return str(e), None

# -------------------------------------------------------
# Payload mapping
# -------------------------------------------------------
def map_payload(container, fields, chat_id):
    uid = str(chat_id)
    date_val = datetime.now().strftime("%Y-%m-%d")

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
            "meal_name": fields.get("meal_name"),
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
            "workout_name": fields.get("workout_name"),
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
# Routing + Telegram
# -------------------------------------------------------
def route_to_container(parsed_json, chat_id):
    if not parsed_json:
        return False, "no_data"

    # Allow either a list or single object
    objs = parsed_json if isinstance(parsed_json, list) else [parsed_json]
    results = []

    for obj in objs:
        c = obj.get("container")
        fields = obj.get("fields", {}) or {}
        table, payload = map_payload(c, fields, chat_id)
        if not table:
            results.append((False, "no_container"))
            continue
        sanitized = sanitize_payload(payload, table)
        if not sanitized:
            results.append((False, "empty_payload"))
            continue
        ok = sb_post(f"/rest/v1/{table}", sanitized)
        results.append((ok, table if ok else "insert_failed"))

    return results

def send_telegram_message(chat_id, text):
    try:
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as e:
        logger.error("Telegram send fail: %s", e)

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
    results = route_to_container(parsed_json, chat_id)

    summary = f"OCR/Transcript preview:\n{text[:400]}\n\nProcessed.\n"
    for ok, label in results:
        summary += f"✅ {label} logged.\n" if ok else f"⚠️ {label} failed.\n"

    send_telegram_message(chat_id, summary)
    return jsonify({"ok": True})

# -------------------------------------------------------
# Run
# -------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))