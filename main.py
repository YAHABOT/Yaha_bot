#!/usr/bin/env python3
import os
import json
import logging
from flask import Flask, request, jsonify
import requests
import openai

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

# Initialize OpenAI client (support new and old python client usage)
openai_client = None
if OPENAI_API_KEY:
    try:
        # Newer openai client exposes an OpenAI client class; try to use it if available
        from openai import OpenAI as OpenAIClient  # type: ignore
        openai_client = OpenAIClient(api_key=OPENAI_API_KEY)
    except Exception:
        # Fall back to older top-level API
        openai.api_key = OPENAI_API_KEY
        openai_client = None

app = Flask(__name__)

TELEGRAM_API_URL = (
    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}" if TELEGRAM_BOT_TOKEN else None
)


def call_openai_for_json(user_text: str):
    """
    Send the user text to OpenAI and request a strict JSON-only reply.
    Returns a tuple (raw_text_response, parsed_json_or_None).
    """
    system_prompt = """
You are a health tracking assistant. Every message from the user should be converted into a structured JSON object for daily tracking.

Respond ONLY with JSON and no explanations.

If the message is about:
- sleep or waking up → container = "sleep"
- workouts or exercise → container = "exercise"
- food, meals, or calories → container = "food"

Format your JSON like this:

{
  "container": "sleep | exercise | food",
  "entry": {
    "description": "short natural summary",
    "fields": {
      "sleep_score": null,
      "energy_score": null,
      "duration": null,
      "start_time": null,
      "end_time": null,
      "resting_hr": null,
      "workout_name": null,
      "duration_min": null,
      "calories_burned": null,
      "intensity": null,
      "items": [],
      "calories": null,
      "protein": null,
      "carbs": null,
      "fat": null
    }
  }
}
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]

    try:
        if openai_client is not None:
            # New client usage
            resp = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=200,
                temperature=0.2,
            )
            ai_text = resp.choices[0].message.content.strip()
        else:
            # Old client usage
            resp = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=200,
                temperature=0.2,
            )
            ai_text = resp.choices[0].message["content"].strip()
    except Exception as e:
        logger.exception("OpenAI request failed")
        ai_text = f"[OpenAI error] {e}"

    parsed = None
    try:
        parsed = json.loads(ai_text)
    except Exception:
        parsed = None

    return ai_text, parsed


def log_to_supabase(entry: dict) -> bool:
    """
    Log the entry to Supabase REST API table `entries`.
    Uses SUPABASE_URL and SUPABASE_ANON_KEY environment variables.
    """
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        logger.warning("Supabase credentials not set; skipping logging")
        return False

    url = SUPABASE_URL.rstrip("/") + "/rest/v1/entries"
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    try:
        r = requests.post(url, headers=headers, json=entry, timeout=10)
        if r.status_code in (200, 201):
            logger.info("Logged entry to Supabase")
            return True
        else:
            logger.warning("Failed to log to Supabase: %s %s", r.status_code, r.text)
            return False
    except Exception:
        logger.exception("Exception while sending to Supabase")
        return False


def send_telegram_message(chat_id: int, text: str) -> bool:
    if not TELEGRAM_API_URL:
        logger.warning("Telegram token not set; cannot send message")
        return False

    url = TELEGRAM_API_URL + "/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            return True
        else:
            logger.warning(
                "Failed to send Telegram message: %s %s", r.status_code, r.text
            )
            return False
    except Exception:
        logger.exception("Exception while sending Telegram message")
        return False


@app.route("/")
def index():
    return jsonify({"status": "ok"})
# ---- OCR + Voice Note Utilities ----
def extract_text_from_image(file_url: str) -> str:
    """
    Uses OCR.Space free API to extract text from an image.
    You must add your OCR_API_KEY as an environment variable on Render.
    Get a free key at https://ocr.space/OCRAPI
    """
    OCR_API_URL = "https://api.ocr.space/parse/imageurl"
    OCR_API_KEY = os.getenv("OCR_API_KEY")
    if not OCR_API_KEY:
        return "[OCR error] Missing OCR_API_KEY"
    try:
        payload = {"apikey": OCR_API_KEY, "url": file_url, "language": "eng"}
        r = requests.post(OCR_API_URL, data=payload, timeout=20)
        result = r.json()
        return result["ParsedResults"][0]["ParsedText"]
    except Exception as e:
        logger.exception("OCR failed")
        return f"[OCR error] {e}"

def transcribe_voice(file_url: str) -> str:
    """
    Downloads a Telegram voice note, converts it to WAV, and transcribes it using SpeechRecognition.
    """
    try:
        ogg_data = requests.get(file_url, timeout=15)
        temp_path = "/tmp/voice.ogg"
        wav_path = "/tmp/voice.wav"

        with open(temp_path, "wb") as f:
            f.write(ogg_data.content)

        from pydub import AudioSegment
        sound = AudioSegment.from_ogg(temp_path)
        sound.export(wav_path, format="wav")

        import speech_recognition as sr
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio = recognizer.record(source)
            text = recognizer.recognize_google(audio)
        return text
    except Exception as e:
        logger.exception("Voice transcription failed")
        return f"[Voice error] {e}"


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True)
    logger.info("Received webhook: %s", data)

    if not data:
        return jsonify({"ok": True})

    # Telegram may send message or edited_message
    message = data.get("message") or data.get("edited_message")
    # Check for image or voice note
if "photo" in message:
    file_id = message["photo"][-1]["file_id"]
    file_info = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={file_id}").json()
    file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_info['result']['file_path']}"
    text = extract_text_from_image(file_url)
elif "voice" in message:
    file_id = message["voice"]["file_id"]
    file_info = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={file_id}").json()
    file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_info['result']['file_path']}"
    text = transcribe_voice(file_url)
else:
    text = message.get("text", "")
    if not message:
        return jsonify({"ok": True})

    text = message.get("text", "")
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not text or not chat_id:
        return jsonify({"ok": True})

    # Call OpenAI for structured JSON
    ai_text, parsed_json = call_openai_for_json(text)

    # Prepare entry to store in Supabase
    entry = {
        "chat_id": str(chat_id),
        "user_message": text,
        "ai_response": ai_text,
        "parsed": bool(parsed_json),
        "parsed_json": parsed_json if parsed_json is not None else None,
    }

    # Log to Supabase (best-effort)
    logged = log_to_supabase(entry)

    # Send a confirmation back to the user
    summary = None
    if parsed_json and isinstance(parsed_json, dict):
        summary = parsed_json.get("reply") if isinstance(parsed_json.get("reply"), str) else None

    confirmation_text = (
        f"Received your message. I've processed it and stored the result{' (parsed JSON)' if parsed_json else ''}."
    )
    if summary:
        confirmation_text += f"\nAssistant reply: {summary}"

    send_telegram_message(chat_id, confirmation_text)

    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
