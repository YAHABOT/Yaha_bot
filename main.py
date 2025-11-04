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
HTTP_TIMEOUT       = int(os.getenv("HTTP_TIMEOUT", "15"))

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
# Table allow-lists (for sanitizer)
# -------------------------------------------------------
TABLE_COLUMNS = {
    "sleep": {"user_id", "date", "sleep_score", "energy_score", "duration_hr", "resting_hr", "notes"},
    "exercise": {"user_id", "date", "workout_name", "distance_km", "duration_min", "calories_burned", "notes"},
    "food": {"user_id", "date", "meal_name", "calories_kcal", "protein_g", "carbs_g", "fat_g", "notes"},
    "entries": {"chat_id", "user_message", "ai_response", "parsed", "parsed_json", "created_at", "notes"},
}

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
        return float(val)
    try:
        m = re.findall(r"[-+]?\d*\.\d+|[-+]?\d+", str(val))
        return float(m[0]) if m else None
    except Exception:
        return None

def sanitize_payload(payload, table):
    allowed = TABLE_COLUMNS.get(table, set())
    if not allowed:
        return payload
    return {k: v for k, v in payload.items() if k in allowed and v is not None}

def sb_post(path, payload):
    url = f"{SUPABASE_URL}{path}"
    r = requests.post(url, headers=sb_headers(), json=payload, timeout=HTTP_TIMEOUT)
    if r.status_code not in (200, 201):
        logger.error("Supabase POST %s: %s\nPayload: %s", r.status_code, r.text, json.dumps(payload))
        return False
    return True

# -------------------------------------------------------
# OCR
# -------------------------------------------------------
def extract_text_from_image(file_url: str) -> str:
    try:
        resp = requests.get(file_url, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        b64_image = base64.b64encode(resp.content).decode("ascii")

        msgs = [
            {"role": "system", "content": "Extract visible text from the image. Plain text only."},
            {"role": "user", "content": [
                {"type": "text", "text": "Extract all readable text."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}}
            ]}
        ]

        if openai_client:
            comp = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=msgs,
                max_tokens=700,
                temperature=0.0,
            )
            return comp.choices[0].message.content.strip()
        else:
            comp = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=msgs,
                max_tokens=700,
                temperature=0.0,
            )
            return comp.choices[0].message["content"].strip()
    except Exception as e:
        logger.exception("OCR error")
        return f"[OCR error] {e}"

# -------------------------------------------------------
# Voice
# -------------------------------------------------------
def transcribe_voice(file_url):
    try:
        ogg = requests.get(file_url, timeout=HTTP_TIMEOUT).content
        tmp_ogg, tmp_wav = "/tmp/voice.ogg", "/tmp/voice.wav"
        with open(tmp_ogg, "wb") as f:
            f.write(ogg)
        AudioSegment.from_ogg(tmp_ogg).export(tmp_wav, format="wav")
        rec = sr.Recognizer()
        with sr.AudioFile(tmp_wav) as src:
            return rec.recognize_google(rec.record(src))
    except Exception as e:
        logger.exception("Voice transcription failed")
        return f"[Voice error] {e}"

# -------------------------------------------------------
# Sleep fallback regex parser
# -------------------------------------------------------
def _parse_duration_hours(text: str):
    m = re.search(r"(\d+)\s*h\s*(\d+)\s*m", text, re.I)
    if not m:
        return None
    h, m_ = int(m.group(1)), int(m.group(2))
    return round(h + m_ / 60.0, 2)

def _parse_sleep_score(text: str):
    m = re.search(r"sleep\s*score.*?(\d+(?:\.\d+)?)", text, re.I)
    if not m:
        return None
    raw = m.group(1)
    cleaned = re.findall(r"\d+", raw)
    return float(cleaned[0]) if cleaned else None

def _parse_energy_score(text: str):
    m = re.search(r"energy\s*score.*?(\d+(?:\.\d+)?)", text, re.I)
    if not m:
        return None
    cleaned = re.findall(r"\d+", m.group(1))
    return float(cleaned[0]) if cleaned else None

def _parse_resting_hr(text: str):
    m = re.search(r"(?:resting\s*hr|avg\.\s*heart\s*rate)[: ]+\s*(\d+)", text, re.I)
    return float(m.group(1)) if m else None

def fallback_parse_sleep_fields(text: str):
    return {
        "sleep_score": _parse_sleep_score(text),
        "energy_score": _parse_energy_score(text),
        "duration_hr": _parse_duration_hours(text),
        "resting_hr": _parse_resting_hr(text),
        "notes": None
    }

# -------------------------------------------------------
# JSON generation (OpenAI)
# -------------------------------------------------------
def call_openai_for_json(user_text):
    system_prompt = (
        "Return ONLY valid JSON with keys: "
        "'container' (sleep|exercise|food|user), "
        "'fields' (object), and 'notes' (string). "
        "Plain JSON, no markdown."
    )
    msgs = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]
    try:
        if openai_client:
            resp = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=msgs,
                max_tokens=300,
                temperature=0.1,
            )
            ai_text = resp.choices[0].message.content.strip()
        else:
            resp = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=msgs,
                max_tokens=300,
                temperature=0.1,
            )
            ai_text = resp.choices[0].message["content"].strip()

        parsed = json.loads(ai_text)
        return ai_text, parsed if isinstance(parsed, dict) else None
    except Exception as e:
        logger.warning("Bad AI response: %s", e)
        return str(e), None

# -------------------------------------------------------
# Mapping into DB rows
# -------------------------------------------------------
def map_payload(container, fields, chat_id):
    ts = now_iso()
    user_id_str = str(chat_id)
    date_val = fields.get("date") or ts[:10]

    if container == "sleep":
        return "sleep", {
            "user_id": None,
            "date": date_val,
            "sleep_score": clean_number(fields.get("sleep_score")),
            "energy_score": clean_number(fields.get("energy_score")),
            "duration_hr": clean_number(fields.get("duration_hr") or fields.get("duration")),
            "resting_hr": clean_number(fields.get("resting_hr")),
            "notes": fields.get("notes"),
        }
    if container == "exercise":
        return "exercise", {
            "user_id": None,
            "date": date_val,
            "workout_name": fields.get("workout_name") or "Workout",
            "distance_km": clean_number(fields.get("distance_km")),
            "duration_min": clean_number(fields.get("duration_min") or fields.get("duration")),
            "calories_burned": clean_number(fields.get("calories_burned") or fields.get("calories_kcal")),
            "notes": fields.get("notes"),
        }
    if container == "food":
        return "food", {
            "user_id": None,
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
# Router with sleep fallback
# -------------------------------------------------------
def route_to_container(original_text, parsed_json, chat_id):
    if not parsed_json:
        if re.search(r"\bsleep\s+score\b|\bsleep\s+time\b", original_text, re.I):
            fields = fallback_parse_sleep_fields(original_text)
            parsed_json = {"container": "sleep", "fields": fields, "notes": ""}

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
        requests.post(
            f"{TELEGRAM_API_URL}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=HTTP_TIMEOUT
        )
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
    data = request.get_json(force=True, silent=True) or {}
    msg = data.get("message") or data.get("edited_message") or {}
    chat_id = msg.get("chat", {}).get("id")
    if not chat_id:
        return jsonify({"ok": True})

    text = ""
    if "photo" in msg:
        try:
            fid = msg["photo"][-1]["file_id"]
            meta = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={fid}", timeout=HTTP_TIMEOUT).json()
            fpath = meta.get("result", {}).get("file_path")
            if not fpath:
                text = "[OCR error] Missing file path."
            else:
                text = extract_text_from_image(f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{fpath}")
        except Exception as e:
            logger.exception("Telegram photo fetch failed")
            text = f"[OCR error] {e}"

    elif "voice" in msg:
        try:
            fid = msg["voice"]["file_id"]
            meta = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={fid}", timeout=HTTP_TIMEOUT).json()
            fpath = meta.get("result", {}).get("file_path")
            if not fpath:
                text = "[Voice error] Missing file path."
            else:
                text = transcribe_voice(f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{fpath}")
        except Exception as e:
            logger.exception("Telegram voice fetch failed")
            text = f"[Voice error] {e}"

    else:
        text = msg.get("text", "")

    ai_text, parsed_json = call_openai_for_json(text)
    ok, status = route_to_container(text, parsed_json, chat_id)
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
