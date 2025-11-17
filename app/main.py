import os
import json
import requests
from flask import Flask, request
from openai import OpenAI

app = Flask(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GPT_PROMPT_ID = os.getenv("GPT_PROMPT_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

client = OpenAI(api_key=OPENAI_API_KEY)

# -----------------------------
# B-MODE SEMI-STRICT JSON REPAIR
# -----------------------------
def repair_json(text: str):
    """
    Fix common JSON issues:
    - Replace Python None/True/False with JSON null/true/false
    - Ensure proper quotes around keys
    - Remove trailing commas
    """
    if not text or not isinstance(text, str):
        return None

    fixed = text.strip()

    # Normalize common issues
    fixed = fixed.replace("None", "null")
    fixed = fixed.replace("True", "true").replace("False", "false")

    # Remove trailing commas before } or ]
    fixed = fixed.replace(",}", "}").replace(",]", "]")

    # If assistant wrapped JSON in code fences
    if fixed.startswith("```"):
        fixed = fixed.strip("`")
        fixed = fixed.replace("json", "")

    # If still invalid JSON it will fail gracefully in json.loads()
    return fixed


# -----------------------------
# PARSE MESSAGE WITH JSON GUARANTEE
# -----------------------------
def parse_message(message_text: str):
    try:
        response = client.responses.create(
            prompt={"id": GPT_PROMPT_ID, "version": "1"},
            input=[{"role": "user", "content": message_text}],
            max_output_tokens=2048
        )
    except Exception as e:
        print("[GPT ERROR]", e)
        return {"container": "unknown", "data": {}, "reply_text": "Sorry, I could not process that."}

    try:
        raw = response.output_text
        print("[GPT RAW]", raw)

        fixed = repair_json(raw)
        print("[GPT FIXED]", fixed)

        parsed = json.loads(fixed)
        return parsed

    except Exception as e:
        print("[JSON ERROR]", e)
        return {"container": "unknown", "data": {}, "reply_text": "Sorry, I could not process that."}


# -----------------------------
# SUPABASE INSERT
# -----------------------------
def supabase_insert(table, payload):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }
    r = requests.post(url, headers=headers, data=json.dumps(payload))
    print("[SUPABASE]", table, r.status_code, r.text)
    return r.status_code == 201 or r.status_code == 204


# -----------------------------
# TELEGRAM SEND MESSAGE
# -----------------------------
def telegram_send(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": chat_id, "text": text})


# -----------------------------
# WEBHOOK
# -----------------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    try:
        msg = data["message"]["text"]
        chat_id = data["message"]["chat"]["id"]
    except:
        return "OK", 200

    parsed = parse_message(msg)
    container = parsed.get("container", "unknown")
    payload = parsed.get("data", {})
    reply_text = parsed.get("reply_text", "Logged.")

    ok = False
    if container == "food":
        ok = supabase_insert("food", payload)
    elif container == "sleep":
        ok = supabase_insert("sleep", payload)
    elif container == "exercise":
        ok = supabase_insert("exercise", payload)

    if not ok:
        reply_text = "Sorry, I could not process that."

    telegram_send(chat_id, reply_text)
    return "OK", 200


@app.route("/")
def index():
    return "YAHA bot running"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)