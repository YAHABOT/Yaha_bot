
import os
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


def send_message(chat_id: str, text: str):
    """
    Sends a simple text message to a Telegram user.
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}

    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print("[TG SEND ERROR]", e)
        pass
