import os
import requests
from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GPT_PROMPT_ID = os.environ.get("GPT_PROMPT_ID")

client = OpenAI(api_key=OPENAI_API_KEY)


# -----------------------------------------------------------
# Helpers
# -----------------------------------------------------------

def tg_send(chat_id: str, text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    requests.post(url, json=payload)


def supabase_insert(table: str, payload: dict):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    r = requests.post(url, json=payload, headers=headers)
    return r.status_code, r.text


# -----------------------------------------------------------
# OpenAI Parser call
# -----------------------------------------------------------

def parse_message(message_text: str):
    response = client.responses.create(
        prompt={"id": GPT_PROMPT_ID, "version": "3"},
        input=[{"role": "user", "content": message_text}],
        max_output_tokens=2048
    )

    # Actual JSON response from output[0].content[0].text
    try:
        raw_text = response.output[0].content[0].text
        return eval(raw_text)  # safe because parser enforced strict JSON
    except Exception as e:
        print("JSON parse error:", e)
        return {
            "container": "unknown",
            "data": {},
            "reply_text": "Sorry, I couldn’t process that."
        }


# -----------------------------------------------------------
# Main Webhook
# -----------------------------------------------------------

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()

    try:
        msg = update["message"]["text"]
        chat_id = str(update["message"]["chat"]["id"])
    except:
        return jsonify({"status": "ignored"})

    parsed = parse_message(msg)

    container = parsed["container"]
    data = parsed["data"]
    reply_text = parsed["reply_text"]

    # Insert based on container
    if container == "food":
        data["chat_id"] = chat_id
        status, body = supabase_insert("food", data)

    elif container == "sleep":
        data["chat_id"] = chat_id
        status, body = supabase_insert("sleep", data)

    elif container == "exercise":
        data["chat_id"] = chat_id
        status, body = supabase_insert("exercise", data)

    else:
        tg_send(chat_id, reply_text)
        return jsonify({"status": "ok"})

    # Supabase response back to user
    if status in (200, 201):
        tg_send(chat_id, reply_text)
    else:
        tg_send(chat_id, "⚠️ I tried to log your entry but Supabase returned an error.")

    return jsonify({"status": "ok"})


@app.route("/", methods=["GET"])
def root():
    return "YAHA bot online.", 200
