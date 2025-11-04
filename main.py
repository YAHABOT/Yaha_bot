#!/usr/bin/env python3
import os, json, logging, requests, base64, re
from datetime import datetime, timezone
from flask import Flask, request, jsonify
import openai
from pydub import AudioSegment
import speech_recognition as sr

# -------------------------------------------------------
# Setup
# -------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("yaha_bot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY")
SUPABASE_URL       = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY  = os.getenv("SUPABASE_ANON_KEY")

openai_client = None
if OPENAI_API_KEY:
    try:
        from openai import OpenAI as OpenAIClient
        openai_client = OpenAIClient(api_key=OPENAI_API_KEY)
    except Exception:
        openai.api_key = OPENAI_API_KEY
        openai_client = None

app = Flask(__name__)
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# -------------------------------------------------------
# Helpers
# -------------------------------------------------------
def now_iso():
    return datetime.now(timezone.utc).isoformat()

def sb_headers():
    return {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

def clean_number(val):
    if val is None: return None
    if isinstance(val, (int, float)): return val
    nums = re.findall(r"[-+]?\d*\.\d+|\d+", str(val))
    return float(nums[0]) if nums else None

def sb_post(path, payload):
    try:
        url = f"{SUPABASE_URL}{path}"
        r = requests.post(url, headers=sb_headers(), json=payload, timeout=15)
        if r.status_code not in (200, 201):
            logger.error("Supabase POST %s: %s\nPayload: %s", r.status_code, r.text, json.dumps(payload))
            return False
        return True
    except Exception as e:
        logger.exception("Supabase insert failed: %s", e)
        return False

# -------------------------------------------------------
# Container Field Map + Detection
# -------------------------------------------------------
FIELD_MAP = {
    "sleep": ["sleep_score", "energy_score", "duration_hr", "resting_hr", "notes"],
    "exercise": ["workout_name", "distance_km", "duration_min", "calories_burned", "notes"],
    "food": ["meal_name", "calories_kcal", "protein_g", "carbs_g", "fat_g", "notes"],
    "user": ["current_weight_kg", "goal_weight_kg", "height_cm"]
}

def detect_container(text):
    text_l = text.lower()
    if "sleep" in text_l: return "sleep"
    if any(w in text_l for w in ["run","gym","exercise","workout"]): return "exercise"
    if any(w in text_l for w in ["meal","food","protein","calorie","breakfast","lunch","dinner"]): return "food"
    if any(w in text_l for w in ["weight","height","goal"]): return "user"
    return "sleep"  # default fallback

def filter_text_for_container(text, container):
    keywords = FIELD_MAP.get(container, [])
    lines = text.splitlines()
    keep = [ln for ln in lines if any(k.replace("_"," ") in ln.lower() for k in keywords)]
    return "\n".join(keep).strip() if keep else text

# -------------------------------------------------------
# OCR + Voice
# -------------------------------------------------------
def extract_text_from_image(file_url):
    try:
        resp = requests.get(file_url, timeout=20)
        resp.raise_for_status()
        b64 = base64.b64encode(resp.content).decode("ascii")
        msgs = [
            {"role": "system", "content": "Extract visible text only. No commentary."},
            {"role": "user", "content": [
                {"type":"text","text":"Extract all readable text."},
                {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}
            ]}
        ]
        if openai_client:
            comp = openai_client.chat.completions.create(model="gpt-4o-mini",messages=msgs,max_tokens=800)
            return comp.choices[0].message.content.strip()
        else:
            comp = openai.ChatCompletion.create(model="gpt-4o-mini",messages=msgs,max_tokens=800)
            return comp.choices[0].message["content"].strip()
    except Exception as e:
        logger.exception("OCR error")
        return f"[OCR error] {e}"

def transcribe_voice(file_url):
    try:
        ogg = requests.get(file_url, timeout=30).content
        tmp_ogg, tmp_wav = "/tmp/voice.ogg", "/tmp/voice.wav"
        with open(tmp_ogg,"wb") as f: f.write(ogg)
        AudioSegment.from_ogg(tmp_ogg).export(tmp_wav,format="wav")
        r = sr.Recognizer()
        with sr.AudioFile(tmp_wav) as src: return r.recognize_google(r.record(src))
    except Exception as e:
        logger.exception("Voice transcription failed")
        return f"[Voice error] {e}"

# -------------------------------------------------------
# OpenAI JSON call
# -------------------------------------------------------
def call_openai_for_json(container, user_text):
    allowed_fields = ", ".join(FIELD_MAP.get(container, []))
    system_prompt = (
        f"You are a JSON generator for a health tracker. "
        f"User data belongs to the '{container}' container. "
        f"Return ONLY valid JSON with keys: 'container', 'fields', 'notes'. "
        f"'fields' may include only: {allowed_fields}. "
        "Output only pure JSON, no text around it."
    )
    msgs = [{"role":"system","content":system_prompt},
             {"role":"user","content":user_text}]
    try:
        if openai_client:
            resp = openai_client.chat.completions.create(model="gpt-4o-mini",messages=msgs,max_tokens=400)
            ai_text = resp.choices[0].message.content.strip()
        else:
            resp = openai.ChatCompletion.create(model="gpt-4o-mini",messages=msgs,max_tokens=400)
            ai_text = resp.choices[0].message["content"].strip()
        parsed = json.loads(ai_text)
        return ai_text, parsed if isinstance(parsed, dict) else None
    except Exception as e:
        logger.warning("Bad AI response: %s", e)
        return str(e), None

# -------------------------------------------------------
# Map + Route
# -------------------------------------------------------
def map_payload(container, fields, chat_id):
    ts = now_iso()
    user_id = str(chat_id)
    base = {"user_id":user_id,"date":fields.get("date") or ts[:10],"notes":fields.get("notes")}
    if container=="sleep":
        base.update({
            "sleep_score":clean_number(fields.get("sleep_score")),
            "energy_score":clean_number(fields.get("energy_score")),
            "duration_hr":clean_number(fields.get("duration_hr")),
            "resting_hr":clean_number(fields.get("resting_hr")),
        })
    elif container=="exercise":
        base.update({
            "workout_name":fields.get("workout_name") or "Workout",
            "distance_km":clean_number(fields.get("distance_km")),
            "duration_min":clean_number(fields.get("duration_min")),
            "calories_burned":clean_number(fields.get("calories_burned")),
        })
    elif container=="food":
        base.update({
            "meal_name":fields.get("meal_name"),
            "calories_kcal":clean_number(fields.get("calories_kcal")),
            "protein_g":clean_number(fields.get("protein_g")),
            "carbs_g":clean_number(fields.get("carbs_g")),
            "fat_g":clean_number(fields.get("fat_g")),
        })
    elif container=="user":
        base.update({
            "current_weight_kg":clean_number(fields.get("current_weight_kg")),
            "goal_weight_kg":clean_number(fields.get("goal_weight_kg")),
            "height_cm":clean_number(fields.get("height_cm")),
        })
    return container, base

def route_to_container(parsed_json, chat_id):
    if not parsed_json or "container" not in parsed_json: return False,"no_container"
    c = parsed_json["container"]
    f = parsed_json.get("fields",{}) or {}
    table, payload = map_payload(c,f,chat_id)
    if not payload: return False,"empty_payload"
    ok = sb_post(f"/rest/v1/{table}",payload)
    return ok, "insert_ok" if ok else "insert_failed"

# -------------------------------------------------------
# Logging + Telegram
# -------------------------------------------------------
def log_entry(chat_id,text,ai_text,parsed_json,status):
    sb_post("/rest/v1/entries",{
        "chat_id":str(chat_id),
        "user_message":text,
        "ai_response":ai_text,
        "parsed":bool(parsed_json),
        "parsed_json":parsed_json,
        "created_at":now_iso(),
        "notes":status
    })

def send_telegram_message(chat_id,text):
    try:
        requests.post(f"{TELEGRAM_API_URL}/sendMessage",
                      json={"chat_id":chat_id,"text":text},timeout=10)
    except Exception:
        logger.exception("Telegram send failed")

# -------------------------------------------------------
# Flask Webhook
# -------------------------------------------------------
@app.route("/")
def index(): return jsonify({"status":"ok"})

@app.route("/webhook",methods=["POST"])
def webhook():
    data = request.get_json(force=True,silent=True)
    msg = data.get("message") or data.get("edited_message") or {}
    chat_id = msg.get("chat",{}).get("id")
    text = ""

    if "photo" in msg:
        fid = msg["photo"][-1]["file_id"]
        fpath = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={fid}",timeout=10).json().get("result",{}).get("file_path")
        text = extract_text_from_image(f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{fpath}") if fpath else "[OCR error]"
    elif "voice" in msg:
        fid = msg["voice"]["file_id"]
        fpath = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={fid}",timeout=10).json().get("result",{}).get("file_path")
        text = transcribe_voice(f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{fpath}") if fpath else "[Voice error]"
    else:
        text = msg.get("text","")

    container = detect_container(text)
    filtered_text = filter_text_for_container(text, container)
    ai_text, parsed_json = call_openai_for_json(container, filtered_text)
    ok, status = route_to_container(parsed_json, chat_id)
    log_entry(chat_id, text, ai_text, parsed_json, status)

    if parsed_json and parsed_json.get("fields"):
        summary = "\n".join(
            [f"{k}: {v}" for k,v in parsed_json["fields"].items() if v not in (None,"",0)]
        )
        msg_txt = f"📦 {parsed_json['container'].capitalize()} data logged:\n{summary}"
    else:
        msg_txt = f"⚠️ Could not parse structured data. Logged text only."
    msg_txt += "\n✅ Saved." if ok else f"\n⚠️ Insert failed: {status}"
    send_telegram_message(chat_id,msg_txt)
    return jsonify({"ok":True})

# -------------------------------------------------------
# Run
# -------------------------------------------------------
if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT",5000)))
