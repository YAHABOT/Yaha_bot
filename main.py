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
    system_prompt = (
        "You are a JSON generator. When given a user message, respond ONLY with a valid JSON object and nothing else. "
        "The JSON must include at least the key \"reply\" with a concise assistant reply. Do not include code fences, markdown, or any extra text."
    )
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
                max_tokens=500,
                temperature=0.2,
            )
            ai_text = resp.choices[0].message.content.strip()
        else:
            # Old client usage
            resp = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=500,
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


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True)
    logger.info("Received webhook: %s", data)

    if not data:
        return jsonify({"ok": True})

    # Telegram may send message or edited_message
    message = data.get("message") or data.get("edited_message")
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
