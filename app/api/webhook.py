from flask import Blueprint, request
from app.parser.engine import parse_message
from app.utils.time import today
from app.services.telegram import send_message
from app.services.supabase import insert_record, log_entry

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
    # GPT PARSING
    # ================================
    try:
        parsed = parse_message(text)
    except Exception as e:
        print("[GPT ERROR]", e)

        # shadow-log parse errors
        log_entry(
            chat_id=chat_id,
            raw_text=text,
            parsed=None,
            container=None,
            error=f"parser_error: {str(e)}",
        )

        send_message(chat_id, "⚠️ Sorry, I could not process that.")
        return "ok", 200

    print("[GPT JSON]", parsed)

    container = parsed.get("container")
    final_data = parsed.get("data", {})
    reply_text = parsed.get("reply_text", "Logged.")

    # ================================
    # UNKNOWN / INVALID CONTAINER
    # ================================
    allowed = {"food", "sleep", "exercise"}

    if container not in allowed:
        print(f"[CONTAINER WARNING] Invalid or unknown container: {container}")

        # shadow-log unknown container
        log_entry(
            chat_id=chat_id,
            raw_text=text,
            parsed=parsed,
            container=container,
            error="invalid_or_unknown_container",
        )

        send_message(
            chat_id,
            "⚠️ I couldn’t classify that as food, sleep, or exercise.\n"
            "Try being a bit more specific.",
        )
        return "ok", 200

    # fill metadata
    final_data["chat_id"] = chat_id
    final_data["date"] = date_val

    print(f"[FINAL DATA → {container}]", final_data)

    # ================================
    # MAIN SUPABASE INSERT
    # ================================
    response, error = insert_record(container, final_data)

    if error:
        print(f"[SUPABASE ERROR {container}]", error)

        # shadow-log failed inserts
        log_entry(
            chat_id=chat_id,
            raw_text=text,
            parsed=parsed,
            container=container,
            error=f"supabase_insert_failed: {error}",
        )

        send_message(chat_id, f"❌ Could not log entry.\n{error}")
        return "ok", 200

    # success
    send_message(chat_id, reply_text)
    return "ok", 200
