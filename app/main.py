import os
from flask import Flask, request
from datetime import datetime
from supabase import create_client, Client
from openai import OpenAI

app = Flask(__name__)

# -------------------------------------------------
# ENV
# -------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GPT_PROMPT_ID = os.getenv("GPT_PROMPT_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# -------------------------------------------------
# INIT CLIENTS
# -------------------------------------------------
client = OpenAI(api_key=OPENAI_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# -------------------------------------------------
# PARSER
# -------------------------------------------------
def parse_message(text: str):
    """Send user text to GPT prompt → get container + structured JSON."""
    try:
        response = client.responses.create(
            prompt={"id": GPT_PROMPT_ID, "version": "1"},
            input=[{"role": "user", "content": text}],
            max_output_tokens=2048
        )
        return response.output[0].content[0].text
    except Exception as e:
        print("GPT PARSE ERROR:", e)
        return None

# -------------------------------------------------
# CLEAN NONE VALUES
# -------------------------------------------------
def clean_dict(d: dict) -> dict:
    """Convert None to actual null values for Supabase insert."""
    return {k: (v if v is not None else None) for k, v in d.items()}

# -------------------------------------------------
# SUPABASE INSERT
# -------------------------------------------------
def insert_into_supabase(container: str, data: dict):
    try:
        result = supabase.table(container).insert(data).execute()
        print(f"[SUPABASE {container}] →", result)
        return result
    except Exception as e:
        print(f"[SUPABASE ERROR {container}] →", e)
        return None

# -------------------------------------------------
# TELEGRAM WEBHOOK
# -------------------------------------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()

    if "message" not in update:
        return "no message", 200

    msg = update["message"]
    chat_id = str(msg["chat"]["id"])
    user_id = str(msg["from"]["id"])
    text = msg.get("text", "")

    print("[TG UPDATE]", update)
    print("[RAW USER TEXT]", text)

    parsed_raw = parse_message(text)
    if parsed_raw is None:
        send_message(chat_id, "❌ Sorry, I could not process that.")
        return "ok", 200

    print("[GPT RAW]", parsed_raw)

    try:
        parsed = eval(parsed_raw)
    except:
        send_message(chat_id, "❌ Invalid structured response.")
        return "ok", 200

    print("[GPT JSON]", parsed)

    container = parsed.get("container", "unknown")
    data = parsed.get("data", {})

    # Add system fields
    data["chat_id"] = chat_id
    data["user_id"] = user_id      # TEXT column now
    data["date"] = datetime.utcnow().strftime("%Y-%m-%d")

    print(f"[FINAL DATA → {container}]:", data)

    clean = clean_dict(data)

    # Insert
    insert_into_supabase(container, clean)

    # Reply
    reply_text = parsed.get("reply_text", "Logged!")
    send_message(chat_id, reply_text)

    return "ok", 200

# -------------------------------------------------
# TELEGRAM SEND MESSAGE
# -------------------------------------------------
import requests

def send_message(chat_id: str, text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=payload)
    except:
        pass

# -------------------------------------------------

@app.route("/")
def home():
    return "YAHA bot alive", 200

# -------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
