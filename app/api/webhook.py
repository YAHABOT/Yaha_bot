from flask import Blueprint, request
from app.parser.engine import parse_message
from app.utils.time import today
from app.services.telegram import send_message
from app.services.supabase import insert_record

api = Blueprint("api", __name__)


@api.route("/", methods=["GET"])
def home():
    return "YAHA bot running"


@api.route("/webhook", methods=["POST"])
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

    container = parsed.get("container")
    final_data = parsed.get("data", {})
    reply_text = parsed.get("reply_text", "✅ Logged successfully.")

    # ================================
    # BASIC CONTAINER VALIDATION
    # ================================
    allowed_containers = {"food", "sleep", "exercise"}

    if container not in allowed_containers:
        print(f"[CONTAINER WARNING] Invalid or unknown container: {container}")
        # Later we can log this to an `entries` table instead.
        send_message(
            chat_id,
            "⚠️ I couldn’t classify that as food, sleep, or exercise,\n"
            "so I didn’t log it. Try being a bit more specific.",
        )
        return "ok", 200

    # Enrich data with metadata
    final_data["chat_id"] = chat_id
    final_data["date"] = date_val

    print(f"[FINAL DATA → {container}]", final_data)

    # ================================
    # SUPABASE INSERT (through service)
    # ================================
    response, error = insert_record(container, final_data)

    if error:
        print(f"[SUPABASE ERROR {container}]", error)
        send_message(chat_id, f"❌ Could not log entry.\n{error}")
        return "ok", 200

    # Success
    send_message(chat_id, reply_text)
    return "ok", 200
