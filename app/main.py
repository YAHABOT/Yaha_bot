import os
from flask import Flask, request
from openai import OpenAI
import requests
import json
from datetime import datetime
import pytz

app = Flask(__name__)

# ----------------------------------------
# ENVIRONMENT VARS
# ----------------------------------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY")
GPT_PROMPT_ID = os.environ.get("GPT_PROMPT_ID")

openai_client = OpenAI(api_key=OPENAI_API_KEY)

# ----------------------------------------
# HELPERS
# ----------------------------------------
def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print("TELEGRAM SEND ERROR:", e)


def today_portugal_date():
    tz = pytz.timezone("Europe/Lisbon")
    return datetime.now(tz).date().isoformat()


# ----------------------------------------
# GPT PARSER (Responses API w/ prompt ID)
# ----------------------------------------
def call_gpt_parser(user_text):
    try:
        response = openai_client.responses.parse(
            model=GPT_PROMPT_ID,
            input=user_text
        )
        return response.output
    except Exception as e:
        print("GPT PARSE ERROR:", e)
        return None


# ----------------------------------------
# SUPABASE INSERT
# ----------------------------------------
def supabase_insert(table, row):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

    print("[SUPABASE] POST", url)
    print("[SUPABASE] PAYLOAD:", row)

    try:
        resp = requests.post(url, headers=headers, data=json.dumps(row))
        print("[SUPABASE] STATUS:", resp.status_code, "BODY:", resp.text)
        return resp.status_code, resp.text
    except Exception as e:
        print("[SUPABASE REQUEST ERROR]", e)
        return 500, str(e)


# ----------------------------------------
# MAIN WEBHOOK
# ----------------------------------------
@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    try:
        update = request.get_json()
        print("[WEBHOOK] Incoming:", update)

        message = update.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        user_text = message.get("text", "")

        if not chat_id:
            return "no chat id", 200

        parsed = call_gpt_parser(user_text)
        print("[GPT RAW]", parsed)

        if parsed is None:
            send_telegram_message(chat_id, "⚠️ Sorry, I could not process that.")
            return "ok", 200

        # MUST be dict with correct keys:
        # { container: "...", data: {...}, reply_text: "..." }
        container = parsed.get("container")
        data = parsed.get("data", {})
        reply_text = parsed.get("reply_text", "Logged it.")

        # --- Auto-fill date if missing ---
        if not data.get("date"):
            data["date"] = today_portugal_date()

        # Always include chat_id + user_id
        data["chat_id"] = str(chat_id)
        data["user_id"] = None  # MVP

        if container not in ["food", "sleep", "exercise"]:
            send_telegram_message(chat_id, "⚠️ I’m not sure what to log.")
            return "ok", 200

        # Insert into Supabase
        status, body = supabase_insert(container, data)

        if status in (200, 201):
            send_telegram_message(chat_id, reply_text)
        else:
            send_telegram_message(chat_id,
                f"⚠️ I tried to log your {container} but Supabase returned an error."
            )

        return "ok", 200

    except Exception as e:
        print("[WEBHOOK ERROR]", e)
        return "ok", 200


# ----------------------------------------
# HEALTH CHECK
# ----------------------------------------
@app.route("/", methods=["GET"])
def home():
    return "OK", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
