import os
from flask import Flask, request
from supabase import create_client, Client
from openai import OpenAI
from datetime import datetime
import pytz

# ================================
# INIT
# ================================
app = Flask(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GPT_PROMPT_ID = os.getenv("GPT_PROMPT_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

client = OpenAI(api_key=OPENAI_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

UTC = pytz.UTC

def today():
    return datetime.now(UTC).strftime("%Y-%m-%d")

# ================================
# PARSE MESSAGE WITH OPENAI
# ================================
def parse_message(message_text: str):
    """
    Sends the user's text to the GPT prompt and expects strict JSON back.
    """
    response = client.responses.create(
        prompt={"id": GPT_PROMPT_ID, "version": "1"},
        input=[{"role": "user", "content": message_text}],
        max_output_tokens=512
    )

    raw = response.output[0].content[0].text
    print("[GPT RAW]", raw)

    import json
    return json.loads(raw)

# ================================
# ROUTES
# ================================
@app.route("/", methods=["GET"])
def home():
    return "YAHA bot running"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print("[TG UPDATE]", data)

    if "message" not in data:
        return "no message", 200

    msg = data["message"]
    chat_id = str(msg["chat"]["id"])
    text = msg.get("text", "")
    date_val = today()

    print("[RAW USER TEXT]", text)

    try:
        parsed = parse_message(text)
    except Exception as e:
        print("[GPT ERROR]", e)
        send_message(chat_id, "⚠️ Sorry, I could not process that.")
        return "ok", 200

    print("[GPT JSON]", parsed)

    container = parsed["container"]
    final_data = parsed["data"]
    final_data["chat_id"] = chat_id
    final_data["date"] = date_val

    print(f"[FINAL DATA → {container}]", final_data)

    # ================================
    # SUPABASE INSERT
    # ================================
    try:
        supabase.table(container).insert(final_data).execute()
        send_message(chat_id, parsed["reply_text"])
    except Exception as e:
        print(f"[SUPABASE ERROR {container}]", e)
        send_message(chat_id, f"❌ Could not log entry.\n{e}")

    return "ok", 200

# ================================
# TG SEND MESSAGE
# ================================
import requests

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=payload)
    except:
        pass

# ================================
# START
# ================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
