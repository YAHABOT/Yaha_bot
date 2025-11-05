#!/usr/bin/env python3
import os, json, logging, requests, base64, re, uuid
from datetime import datetime, timezone
from flask import Flask, request, jsonify
import openai
from pydub import AudioSegment
import speech_recognition as sr

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("yaha_bot")

# -------------------------------------------------------
# Environment setup
# -------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY")
SUPABASE_URL       = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY  = os.getenv("SUPABASE_ANON_KEY")

app = Flask(__name__)
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# OpenAI setup
openai_client = None
if OPENAI_API_KEY:
    try:
        from openai import OpenAI as OpenAIClient
        openai_client = OpenAIClient(api_key=OPENAI_API_KEY)
    except Exception:
        openai.api_key = OPENAI_API_KEY
        openai_client = None


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
    if val is None:
        return None
    try:
        nums = re.findall(r"[-+]?\d*\.\d+|\d+", str(val))
        return float(nums[0]) if nums else None
    except Exception:
        return None


# -------------------------------------------------------
# Verbose Supabase POST (fix #3)
# -------------------------------------------------------
def sb_post(path, payload):
    url = f"{SUPABASE_URL}{path}"
    try:
        r = requests.post(url, headers=sb_headers(), json=payload, timeout=15)
        logger.info(f"POST {url} -> {r.status_code}: {r.text}")
        if r.status_code not in (200, 201):
            return False
        return True
    except Exception as e:
        logger.error(f"Supabase POST exception: {e}")
        return False


# -------------------------------------------------------
# Schema definitions
# -------------------------------------------------------
SCHEMA = {
    "sleep": {
        "sleep_score": "float",
        "energy_score": "float",
        "duration_hr": "float",
        "resting_hr": "float",
        "notes": "string"
    },
    "food": {
        "meal_name": "string",
        "calories": "float",
        "protein_g": "float",
        "carbs_g": "float",
        "fat_g": "float",
        "fiber_g": "float",
        "notes": "string"
    },
    "exercise": {
        "workout_name": "string",
        "distance_km": "float",
        "duration_min": "float",
        "calories_burned": "float",
        "training_intensity": "float",
        "avg_hr": "float",
        "notes": "string"
    }
}


# -------------------------------------------------------
# OCR + Voice
# -------------------------------------------------------
def extract_text_from_image(file_url):
    try:
        img = requests.get(file_url, timeout=20).content
        b64 = base64.b64encode(img).decode("ascii")
        msgs = [
            {"role": "system", "content": "Extract visible text, no commentary."},
            {"role": "user", "content": [
                {"type": "text", "text": "Extract all readable text clearly."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
            ]}
        ]
        if openai_client:
            res = openai_client.chat.completions.create(model="gpt-4o-mini", messages=msgs, max_tokens=1200)
            return res.choices[0].message.content.strip()
        else:
            res = openai.ChatCompletion.create(model="gpt-4o-mini", messages=msgs, max_tokens=1200)
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
# OpenAI structured extraction (with food fallback)
# -------------------------------------------------------
def call_openai_for_json(user_text):
    schema_str = json.dumps(SCHEMA, indent=2)
    sys_prompt = (
        "You are a structured data extractor for a health tracker. "
        "Return ONLY valid JSON, one object per container in this schema:\n"
        f"{schema_str}\n"
        "If nutritional data (Calories, Protein, Carbs, Fat) is detected, assume container='food'. "
        "Never guess missing fields. Ignore irrelevant text. "
        "Example output:\n"
        "[{'container':'sleep','fields':{'sleep_score':88.3},'notes':'summary'}]"
    )

    msgs = [{"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_text}]

    try:
        if openai_client:
            res = openai_client.chat.completions.create(model="gpt-4o-mini", messages=msgs, max_tokens=900)
            txt = res.choices[0].message.content.strip()
        else:
            res = openai.ChatCompletion.create(model="gpt-4o-mini", messages=msgs, max_tokens=900)
            txt = res.choices[0].message["content"].strip()
        parsed = json.loads(txt)
    except Exception as e:
        logger.warning("AI parse failed: %s", e)
        return str(e), None

    if isinstance(parsed, dict):
        parsed = [parsed]

    cleaned = []
    for obj in parsed:
        c = str(obj.get("container", "")).lower().strip()   # fix #2 lowercase normalize
        if c not in SCHEMA:
            continue
        fields = {}
        for key, dtype in SCHEMA[c].items():
            val = obj.get("fields", {}).get(key)
            if val not in (None, "", "null"):
                if dtype == "float":
                    val = clean_number(val)
                if val not in (None, 0, "0"):
                    fields[key] = val
        if fields:
            cleaned.append({"container": c, "fields": fields, "notes": obj.get("notes", "")})
    return json.dumps(cleaned), cleaned


# -------------------------------------------------------
# Data routing
# -------------------------------------------------------
def map_payload(container, fields, chat_id):
    uid = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(chat_id)))  # deterministic UUID
    base = {
        "user_id": uid,
        "date": datetime.now().strftime("%Y-%m-%d"),
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
        flds = obj.get("fields", {})
        table, payload = map_payload(c, flds, chat_id)
        if not flds:
            results.append((False, f"{c}:empty"))
            continue
        ok = sb_post(f"/{table}", payload)
        results.append((ok, f"{c}:ok" if ok else f"{c}:fail"))
    return results


# -------------------------------------------------------
# Telegram
# -------------------------------------------------------
def send_telegram_message(chat_id, text):
    try:
        requests.post(f"{TELEGRAM_API_URL}/sendMessage",
                      json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as e:
        logger.error("Telegram send error: %s", e)


# -------------------------------------------------------
# Webhook
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
        text = ""

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
        results = route_to_container(parsed, chat_id)

        # concise Telegram summary
        preview = text[:300].replace("\n", " ")
        summary = f"Processed: {preview}\n\n"
        if parsed:
            for p in parsed:
                c = p['container']
                fields = ", ".join(f"{k}:{v}" for k,v in p['fields'].items())
                summary += f"✅ {c} → {fields}\n"
        else:
            summary += "⚠️ No valid container detected.\n"
        send_telegram_message(chat_id, summary)
        return jsonify({"ok": True})

    except Exception as e:
        logger.error("Webhook exception: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500


# -------------------------------------------------------
# Run
# -------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
