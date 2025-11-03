#!/usr/bin/env python3
import os
import json
import logging
import requests
import base64
from datetime import datetime, timezone
from flask import Flask, request, jsonify
import openai
from pydub import AudioSegment
import speech_recognition as sr

# -------------------------------
# Logging
# -------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("yaha_bot")

# -------------------------------
# Env
# -------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY")
SUPABASE_URL       = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY  = os.getenv("SUPABASE_ANON_KEY")

# OpenAI client (new SDK if available, else legacy)
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

# -------------------------------
# Helpers
# -------------------------------
def now_iso():
    return datetime.now(timezone.utc).isoformat()

def sb_headers():
    return {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

def sb_post(path, payload):
    url = f"{SUPABASE_URL}{path}"
    r = requests.post(url, headers=sb_headers(), json=payload, timeout=15)
    ok = r.status_code in (200, 201)
    if not ok:
        logger.error("Supabase POST failed %s: %s | payload=%s",
                     r.status_code, r.text, json.dumps(payload)[:4000])
    return ok, r

def sb_patch(path, payload):
    url = f"{SUPABASE_URL}{path}"
    r = requests.patch(url, headers=sb_headers(), json=payload, timeout=15)
    ok = r.status_code in (200, 201, 204)
    if not ok:
        logger.error("Supabase PATCH failed %s: %s | payload=%s",
                     r.status_code, r.text, json.dumps(payload)[:4000])
    return ok, r

# -------------------------------
# OCR (OpenAI Vision)
# -------------------------------
def extract_text_from_image(file_url: str) -> str:
    try:
        resp = requests.get(file_url, timeout=20)
        resp.raise_for_status()
        b64_image = base64.b64encode(resp.content).decode("ascii")

        messages = [
            {
                "role": "system",
                "content": (
                    "You extract plain text from screenshots. "
                    "Return only readable text. No commentary."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract all readable text from this image."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}}
                ],
            },
        ]

        if openai_client:
            comp = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=1200,
                temperature=0.0,
            )
            return comp.choices[0].message.content.strip()
        else:
            comp = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=1200,
                temperature=0.0,
            )
            return comp.choices[0].message["content"].strip()
    except Exception as e:
        logger.exception("OCR error")
        return f"[OCR error] {e}"

# -------------------------------
# Voice → text
# -------------------------------
def transcribe_voice(file_url):
    try:
        ogg = requests.get(file_url, timeout=30).content
        tmp_ogg = "/tmp/voice.ogg"
        tmp_wav = "/tmp/voice.wav"
        with open(tmp_ogg, "wb") as f:
            f.write(ogg)
        AudioSegment.from_ogg(tmp_ogg).export(tmp_wav, format="wav")

        rec = sr.Recognizer()
        with sr.AudioFile(tmp_wav) as src:
            audio = rec.record(src)
            return rec.recognize_google(audio)
    except Exception as e:
        logger.exception("Voice transcription failed")
        return f"[Voice error] {e}"

# -------------------------------
# LLM → structured JSON
# -------------------------------
def call_openai_for_json(user_text):
    system_prompt = (
        "You are a JSON generator for a health tracking assistant. "
        "Return only a JSON object with keys: "
        "'container' (one of: sleep, exercise, food, user), "
        "'fields' (object of data points), "
        "'notes' (string). "
        "Do NOT include code fences or extra text."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]

    try:
        if openai_client:
            resp = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=250,
                temperature=0.2,
            )
            ai_text = resp.choices[0].message.content.strip()
        else:
            resp = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=250,
                temperature=0.2,
            )
            ai_text = resp.choices[0].message["content"].strip()
    except Exception as e:
        logger.exception("OpenAI request failed")
        return f"[OpenAI error] {e}", None

    try:
        parsed = json.loads(ai_text)
    except Exception:
        parsed = None

    return ai_text, parsed

# -------------------------------
# Field mapping → your tables
# -------------------------------
def map_payload(container, fields, chat_id):
    """
    Map the LLM 'fields' to your actual Supabase table columns.
    Current table columns per your screenshots:

    sleep(id, user_id, date, sleep_score, energy_score, duration_hr, resting_hr, notes)
    exercise(id, user_id, date, duration_min, calories_kcal, avg_hr, max_hr, notes)
    food(id, user_id, date, meal_name, calories_kcal, protein_g, carbs_g, fat_g, notes)
    users(chat_id pk/unique?, current_weight_kg, height_cm, tdee_goal_kcal, ...)
    weight_history(id, user_id, weight_kg, timestamp)
    """
    ts = now_iso()
    # Accept either 'date' provided by LLM, or use UTC date
    date_val = fields.get("date") or ts[:10]

    if container == "sleep":
        return "sleep", {
            "user_id": str(chat_id),
            "date": date_val,
            "sleep_score": fields.get("sleep_score"),
            "energy_score": fields.get("energy_score"),
            "duration_hr": fields.get("duration_hr") or fields.get("duration"),
            "resting_hr": fields.get("resting_hr"),
            "notes": fields.get("notes"),
        }

    if container == "exercise":
        return "exercise", {
            "user_id": str(chat_id),
            "date": date_val,
            "duration_min": fields.get("duration_min") or fields.get("duration_minutes"),
            "calories_kcal": fields.get("calories_kcal") or fields.get("tdee_kcal"),
            "avg_hr": fields.get("avg_hr") or fields.get("average_hr"),
            "max_hr": fields.get("max_hr"),
            "notes": fields.get("notes"),
        }

    if container == "food":
        return "food", {
            "user_id": str(chat_id),
            "date": date_val,
            "meal_name": fields.get("meal_name") or fields.get("name"),
            "calories_kcal": fields.get("calories_kcal"),
            "protein_g": fields.get("protein_g"),
            "carbs_g": fields.get("carbs_g"),
            "fat_g": fields.get("fat_g"),
            "notes": fields.get("notes"),
        }

    if container == "user":
        # For weight updates, we patch users and insert into weight_history
        # Return a special marker the router will act on.
        mapped = {
            "current_weight_kg": fields.get("current_weight_kg"),
            "height_cm": fields.get("height_cm"),
            "tdee_goal_kcal": fields.get("tdee_goal_kcal"),
        }
        return "user", mapped

    return None, None

# -------------------------------
# Route to Supabase tables
# -------------------------------
def route_to_container(parsed_json, chat_id):
    if not parsed_json or "container" not in parsed_json:
        return False, "no_container"

    container = parsed_json["container"]
    fields = parsed_json.get("fields", {}) or {}
    table, payload = map_payload(container, fields, chat_id)

    if table is None:
        logger.warning("Unknown container: %s", container)
        return False, "unknown_container"

    # Special handling for user weight updates
    if table == "user":
        did_any = False
        if payload.get("current_weight_kg") is not None:
            # patch users
            ok1, _ = sb_patch(f"/rest/v1/users?chat_id=eq.{chat_id}", {
                "current_weight_kg": payload["current_weight_kg"]
            })
            # insert weight_history
            ok2, _ = sb_post("/rest/v1/weight_history", {
                "user_id": str(chat_id),
                "weight_kg": payload["current_weight_kg"],
                "timestamp": now_iso(),
            })
            did_any = ok1 and ok2
            if not did_any:
                return False, "user_weight_write_failed"
        # optional patches for height / tdee_goal
        if payload.get("height_cm") is not None:
            sb_patch(f"/rest/v1/users?chat_id=eq.{chat_id}", {"height_cm": payload["height_cm"]})
        if payload.get("tdee_goal_kcal") is not None:
            sb_patch(f"/rest/v1/users?chat_id=eq.{chat_id}", {"tdee_goal_kcal": payload["tdee_goal_kcal"]})
        return True, "user_updated" if did_any else "user_patched"

    # Normal container insert
    ok, _ = sb_post(f"/rest/v1/{table}", payload)
    return (ok, "insert_ok" if ok else "insert_failed")

# -------------------------------
# Audit log in entries
# -------------------------------
def log_entry(chat_id, user_message, ai_text, parsed_json, note):
    payload = {
        "chat_id": str(chat_id),
        "user_message": user_message,
        "ai_response": ai_text,
        "parsed": bool(parsed_json),
        "parsed_json": parsed_json,
        "created_at": now_iso(),
        "notes": note,
    }
    ok, _ = sb_post("/rest/v1/entries", payload)
    if not ok:
        logger.error("Failed to write audit entry.")

# -------------------------------
# Telegram
# -------------------------------
def send_telegram_message(chat_id, text):
    try:
        requests.post(
            f"{TELEGRAM_API_URL}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except Exception:
        logger.exception("Failed to send Telegram message.")

# -------------------------------
# Flask routes
# -------------------------------
@app.route("/")
def index():
    return jsonify({"status": "ok"})

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"ok": True})

    message = data.get("message") or data.get("edited_message")
    if not message:
        return jsonify({"ok": True})

    chat = message.get("chat", {}) or {}
    chat_id = chat.get("id")
    if not chat_id:
        return jsonify({"ok": True})

    # Ingest
    if "photo" in message:
        file_id = message["photo"][-1]["file_id"]
        finfo = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={file_id}", timeout=15).json()
        fpath = finfo.get("result", {}).get("file_path")
        text = extract_text_from_image(f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{fpath}") if fpath else "[OCR error] Missing file path."
    elif "voice" in message:
        file_id = message["voice"]["file_id"]
        finfo = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={file_id}", timeout=15).json()
        fpath = finfo.get("result", {}).get("file_path")
        text = transcribe_voice(f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{fpath}") if fpath else "[Voice error] Missing file path."
    else:
        text = message.get("text", "")

    if not text:
        return jsonify({"ok": True})

    # Structure with LLM
    ai_text, parsed_json = call_openai_for_json(text)

    # Route to table
    success, status = route_to_container(parsed_json, chat_id)

    # Audit
    log_entry(chat_id, text, ai_text, parsed_json, status)

    # Reply
    preview = ""
    if ("photo" in message or "voice" in message) and text:
        cut = text[:600] + ("…" if len(text) > 600 else "")
        preview = f"OCR/Transcript preview:\n{cut}\n\n"

    tail = "Saved." if success else f"Saved to log, but container insert failed ({status})."
    if parsed_json and isinstance(parsed_json, dict) and parsed_json.get("notes"):
        tail += f"\nNotes: {parsed_json['notes']}"

    send_telegram_message(chat_id, f"{preview}Received and processed your message.\n{tail}")
    return jsonify({"ok": True})

# -------------------------------
# Run
# -------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
