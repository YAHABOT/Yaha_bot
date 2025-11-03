#!/usr/bin/env python3
import os
import json
import logging
import requests
import base64
from datetime import datetime
from flask import Flask, request, jsonify
import openai
from pydub import AudioSegment
import speech_recognition as sr

# -------------------------------------------------------
# Logging setup
# -------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------------------------------------------
# Environment variables
# -------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

# Initialize OpenAI
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
# OCR via OpenAI Vision
# -------------------------------------------------------
def extract_text_from_image(file_url: str) -> str:
    try:
        logger.info("Downloading image for OCR...")
        resp = requests.get(file_url, timeout=20)
        resp.raise_for_status()
        img_bytes = resp.content
        b64_image = base64.b64encode(img_bytes).decode("ascii")

        vision_messages = [
            {
                "role": "system",
                "content": (
                    "You extract text from screenshots. Return only readable text. "
                    "No image descriptions or explanations."
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

        logger.info("Calling OpenAI Vision for OCR...")
        if openai_client:
            comp = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=vision_messages,
                max_tokens=1000,
                temperature=0.0,
            )
            text = comp.choices[0].message.content.strip()
        else:
            comp = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=vision_messages,
                max_tokens=1000,
                temperature=0.0,
            )
            text = comp.choices[0].message["content"].strip()

        return text if text else "[No text found in image]"
    except Exception as e:
        logger.exception("OCR error")
        return f"[OCR error] {e}"

# -------------------------------------------------------
# Voice Note Transcription
# -------------------------------------------------------
def transcribe_voice(file_url):
    try:
        logger.info("Transcribing voice note...")
        ogg_data = requests.get(file_url, timeout=30).content
        temp_ogg = "/tmp/voice.ogg"
        temp_wav = "/tmp/voice.wav"

        with open(temp_ogg, "wb") as f:
            f.write(ogg_data)

        sound = AudioSegment.from_ogg(temp_ogg)
        sound.export(temp_wav, format="wav")

        recognizer = sr.Recognizer()
        with sr.AudioFile(temp_wav) as source:
            audio = recognizer.record(source)
            text = recognizer.recognize_google(audio)

        return text
    except Exception as e:
        logger.exception("Voice transcription failed")
        return f"[Voice error] {e}"

# -------------------------------------------------------
# OpenAI → JSON Structuring
# -------------------------------------------------------
def call_openai_for_json(user_text):
    system_prompt = (
        "You are a JSON generator for a health tracking assistant. "
        "Return only a valid JSON object with: "
        "'container' (sleep|exercise|food|user), "
        "'fields' (dictionary of data points), and 'notes' (string). "
        "Do not include markdown or text outside JSON."
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
                max_tokens=200,
                temperature=0.2,
            )
            ai_text = resp.choices[0].message.content.strip()
        else:
            resp = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=200,
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

# -------------------------------------------------------
# Field Parsing Layer
# -------------------------------------------------------
def parse_fields_from_text(container: str, text: str) -> dict:
    """Parses OCR/transcript text and extracts structured fields per container."""
    fields = {}
    lines = text.lower().splitlines()

    try:
        # --- Sleep ---
        if container == "sleep":
            for line in lines:
                if "energy score" in line:
                    fields["energy_score"] = ''.join([c for c in line if c.isdigit()])
                elif "sleep score" in line:
                    fields["sleep_score"] = ''.join([c for c in line if c.isdigit()])
                elif "sleep time" in line and ("h" in line or "m" in line):
                    fields["sleep_time"] = line.strip()
                elif "actual sleep" in line:
                    fields["actual_sleep"] = line.strip()
                elif "rem" in line:
                    fields["rem_quality"] = line.strip()
                elif "deep" in line:
                    fields["deep_sleep"] = line.strip()
                elif "awake" in line:
                    fields["awake_time"] = line.strip()

        # --- Exercise ---
        elif container == "exercise":
            for line in lines:
                if "steps" in line:
                    fields["steps"] = ''.join([c for c in line if c.isdigit()])
                elif "distance" in line or "km" in line:
                    fields["distance_km"] = ''.join([c for c in line if c.isdigit() or c == '.'])
                elif "tdee" in line:
                    fields["tdee"] = ''.join([c for c in line if c.isdigit()])
                elif "neat" in line:
                    fields["neat"] = ''.join([c for c in line if c.isdigit()])
                elif "intensity" in line:
                    fields["training_intensity"] = ''.join([c for c in line if c.isdigit()])

        # --- Food ---
        elif container == "food":
            for line in lines:
                if "calories" in line or "kcal" in line:
                    fields["calories"] = ''.join([c for c in line if c.isdigit()])
                elif "protein" in line or "p:" in line:
                    fields["protein_g"] = ''.join([c for c in line if c.isdigit() or c == '.'])
                elif "carb" in line or "c:" in line:
                    fields["carbs_g"] = ''.join([c for c in line if c.isdigit() or c == '.'])
                elif "fat" in line or "f:" in line:
                    fields["fat_g"] = ''.join([c for c in line if c.isdigit() or c == '.'])
                elif "meal" in line or "wrap" in line or "bowl" in line:
                    fields["meal_name"] = line.strip()

        # --- User ---
        elif container == "user":
            for line in lines:
                if "weight" in line:
                    try:
                        fields["current_weight_kg"] = float(''.join([c for c in line if c.isdigit() or c == '.']))
                    except:
                        pass
                elif "height" in line:
                    fields["height_cm"] = ''.join([c for c in line if c.isdigit()])
                elif "goal" in line and "weight" in line:
                    fields["goal_weight_kg"] = ''.join([c for c in line if c.isdigit() or c == '.'])
                elif "bmr" in line:
                    fields["bmr"] = ''.join([c for c in line if c.isdigit()])

    except Exception as e:
        logger.exception(f"Error while parsing {container}: {e}")

    fields["timestamp"] = datetime.utcnow().isoformat()
    return fields

# -------------------------------------------------------
# Supabase Routing
# -------------------------------------------------------
def route_to_container(parsed_json, chat_id):
    if not parsed_json or "container" not in parsed_json:
        return False

    container = parsed_json["container"]
    fields = parsed_json.get("fields", {})
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
    }

    try:
        if container == "user" and "current_weight_kg" in fields:
            weight = fields["current_weight_kg"]
            requests.patch(
                f"{SUPABASE_URL}/rest/v1/users?chat_id=eq.{chat_id}",
                headers=headers,
                json={"current_weight_kg": weight},
            )
            requests.post(
                f"{SUPABASE_URL}/rest/v1/weight_history",
                headers=headers,
                json={"user_id": chat_id, "weight_kg": weight, "timestamp": fields["timestamp"]},
            )
            return True

        if container in ["sleep", "exercise", "food"]:
            fields["chat_id"] = chat_id
            requests.post(
                f"{SUPABASE_URL}/rest/v1/{container}",
                headers=headers,
                json=fields,
            )
            return True

        return False

    except Exception as e:
        logger.exception(f"Failed routing to {container}: {e}")
        return False

# -------------------------------------------------------
# Supabase Logging
# -------------------------------------------------------
def log_to_supabase(entry):
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        logger.warning("Supabase not configured.")
        return False

    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/entries"
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    try:
        r = requests.post(url, headers=headers, json=entry, timeout=10)
        return r.status_code in (200, 201)
    except Exception:
        logger.exception("Failed to log to Supabase.")
        return False

# -------------------------------------------------------
# Telegram Messaging
# -------------------------------------------------------
def send_telegram_message(chat_id, text):
    try:
        url = f"{TELEGRAM_API_URL}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        requests.post(url, json=payload, timeout=10)
    except Exception:
        logger.exception("Failed to send Telegram message.")

# -------------------------------------------------------
# Flask Webhook
# -------------------------------------------------------
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

    text = ""
    chat = message.get("chat", {}) or {}
    chat_id = chat.get("id")

    # --- Handle photo input ---
    if "photo" in message:
        file_id = message["photo"][-1]["file_id"]
        file_info = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={file_id}", timeout=15).json()
        file_path = file_info.get("result", {}).get("file_path")
        if file_path:
            file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
            text = extract_text_from_image(file_url)
        else:
            text = "[OCR error] Missing file path."

    # --- Handle voice input ---
    elif "voice" in message:
        file_id = message["voice"]["file_id"]
        file_info = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={file_id}", timeout=15).json()
        file_path = file_info.get("result", {}).get("file_path")
        if file_path:
            file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
            text = transcribe_voice(file_url)
        else:
            text = "[Voice error] Missing file path."

    # --- Handle text input ---
    else:
        text = message.get("text", "")

    if not chat_id or not text:
        return jsonify({"ok": True})

    ai_text, parsed_json = call_openai_for_json(text)
    if parsed_json:
        container = parsed_json.get("container")
        detected_fields = parse_fields_from_text(container, text)
        parsed_json["fields"].update(detected_fields)
        route_to_container(parsed_json, chat_id)

    entry = {
        "chat_id": str(chat_id),
        "user_message": text,
        "ai_response": ai_text,
        "parsed": bool(parsed_json),
        "parsed_json": parsed_json,
        "timestamp": datetime.utcnow().isoformat(),
    }
    log_to_supabase(entry)

    confirmation = "Received and processed your message."
    if ("photo" in message or "voice" in message) and text:
        preview = (text[:300] + "…") if len(text) > 300 else text
        confirmation = f"OCR/Transcript preview:\n{preview}\n\n" + confirmation

    if parsed_json and isinstance(parsed_json, dict) and parsed_json.get("notes"):
        confirmation += f"\nNotes: {parsed_json['notes']}"

    send_telegram_message(chat_id, confirmation)
    return jsonify({"ok": True})

# -------------------------------------------------------
# Run Server
# -------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
