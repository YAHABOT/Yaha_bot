#!/usr/bin/env python3
import os
import json
import logging
import requests
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
OCR_API_KEY = os.getenv("OCR_API_KEY")

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
# OCR Function (Real OCR.Space Integration)
# -------------------------------------------------------
def extract_text_from_image(file_url: str) -> str:
    """
    Extract text from an image using OCR.Space.
    Expects a Telegram file URL that is publicly retrievable via your bot token.
    """
    if not OCR_API_KEY:
        logger.warning("OCR_API_KEY not set; returning placeholder.")
        return "[OCR disabled: missing OCR_API_KEY]"

    try:
        payload = {
            "apikey": OCR_API_KEY,
            "url": file_url,
            "language": "eng",
            "OCREngine": 2,
            "isTable": True,
            "scale": True
        }
        r = requests.post("https://api.ocr.space/parse/image", data=payload, timeout=30)
        r.raise_for_status()
        data = r.json()

        if data.get("IsErroredOnProcessing"):
            err = data.get("ErrorMessage") or data.get("ErrorDetails") or "Unknown OCR error"
            if isinstance(err, list):
                err = "; ".join(err)
            return f"[OCR error] {err}"

        results = data.get("ParsedResults", [])
        if not results:
            return "[OCR found no text]"
        text = results[0].get("ParsedText", "").strip()
        return text or "[OCR found no text]"
    except Exception as e:
        logger.exception("OCR call failed")
        return f"[OCR error] {e}"

# -------------------------------------------------------
# Voice Note Transcription
# -------------------------------------------------------
def transcribe_voice(file_url):
    try:
        logger.info("Transcribing voice note...")
        ogg_data = requests.get(file_url).content
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
# OpenAI Interaction
# -------------------------------------------------------
def call_openai_for_json(user_text):
    system_prompt = (
        "You are a JSON generator for a health tracking assistant. "
        "When given a user message, respond ONLY with a valid JSON object "
        "containing keys like 'container' (sleep/exercise/food), 'value', and 'notes'."
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
# Telegram Message Sending
# -------------------------------------------------------
def send_telegram_message(chat_id, text):
    url = f"{TELEGRAM_API_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception:
        logger.exception("Failed to send Telegram message.")

# -------------------------------------------------------
# Flask Routes
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
    chat_id = message.get("chat", {}).get("id")

    # Handle images and voice
    if "photo" in message:
        file_id = message["photo"][-1]["file_id"]
        file_info = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={file_id}").json()
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_info['result']['file_path']}"
        text = extract_text_from_image(file_url)
        send_telegram_message(chat_id, f"OCR preview:\n{text[:200]}")

    elif "document" in message and str(message["document"].get("mime_type", "")).startswith("image/"):
        file_id = message["document"]["file_id"]
        file_info = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={file_id}").json()
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_info['result']['file_path']}"
        text = extract_text_from_image(file_url)
        send_telegram_message(chat_id, f"OCR preview:\n{text[:200]}")

    elif "voice" in message:
        file_id = message["voice"]["file_id"]
        file_info = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={file_id}").json()
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_info['result']['file_path']}"
        text = transcribe_voice(file_url)

    else:
        text = message.get("text", "")

    if not chat_id or not text:
        return jsonify({"ok": True})

    ai_text, parsed_json = call_openai_for_json(text)

    entry = {
        "chat_id": str(chat_id),
        "user_message": text,
        "ai_response": ai_text,
        "parsed": bool(parsed_json),
        "parsed_json": parsed_json,
    }

    log_to_supabase(entry)

    response_text = "Received and processed your message."
    if parsed_json and isinstance(parsed_json, dict) and "notes" in parsed_json:
        response_text += f"\nNotes: {parsed_json['notes']}"

    send_telegram_message(chat_id, response_text)
    return jsonify({"ok": True})

# -------------------------------------------------------
# Run App
# -------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
