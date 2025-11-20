import os
from flask import Flask, request
from supabase import create_client, Client
from openai import OpenAI
from datetime import datetime
import pytz

# ================================
# IMPORT MOVED MODULES
# ================================
from app.parser.engine import parse_message
from app.utils.time import today
from app.services.telegram import send_message
from app.services.supabase import insert_record

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

    # ================================
    # GPT PARSER
    # ================================
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
    # SUPABASE INSERT (through the service)
    # ================================
    response, error = insert_record(container, final_data)

    if error:
        print(f"[SUPABASE ERROR {container}]", error)
        send_message(chat_id, f"❌ Could not log entry.\n{error}")
        return "ok", 200

    # Success
    send_message(chat_id, parsed["reply_text"])
    return "ok", 200


# ================================
# START
# ================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
