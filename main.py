#!/usr/bin/env python3
import os, json, logging, requests, base64, re, functools
from datetime import datetime, timezone
from flask import Flask, request, jsonify
import openai
from pydub import AudioSegment
import speech_recognition as sr

# =========================
# Basic setup
# =========================
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("yaha")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY")
SUPABASE_URL       = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY  = os.getenv("SUPABASE_ANON_KEY")

app = Flask(__name__)
TG = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# OpenAI client (handles both new and legacy import styles)
openai_client = None
if OPENAI_API_KEY:
    try:
        from openai import OpenAI as OpenAIClient
        openai_client = OpenAIClient(api_key=OPENAI_API_KEY)
    except Exception:
        openai.api_key = OPENAI_API_KEY
        openai_client = None

# =========================
# Helpers
# =========================
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def sb_headers():
    return {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

def sb_post(path: str, payload: dict, timeout=20):
    url = f"{SUPABASE_URL}{path}"
    r = requests.post(url, headers=sb_headers(), json=payload, timeout=timeout)
    if r.status_code not in (200, 201):
        log.error("POST %s -> %s :: %s", path, r.status_code, r.text)
        return None
    try:
        return r.json()
    except Exception:
        return []

def sb_patch(path: str, payload: dict, timeout=20):
    url = f"{SUPABASE_URL}{path}"
    r = requests.patch(url, headers=sb_headers(), json=payload, timeout=timeout)
    if r.status_code not in (200, 201, 204):
        log.error("PATCH %s -> %s :: %s", path, r.status_code, r.text)
        return None
    return True

def sb_get(path: str, params=None, timeout=20):
    url = f"{SUPABASE_URL}{path}"
    r = requests.get(url, headers=sb_headers(), params=params or {}, timeout=timeout)
    if r.status_code not in (200, 206):
        log.error("GET %s -> %s :: %s", path, r.status_code, r.text)
        return None
    try:
        return r.json()
    except Exception:
        return []

def clean_number(val):
    if val is None: return None
    if isinstance(val, (int, float)): return float(val)
    found = re.findall(r"[-+]?\d*\.\d+|[-+]?\d+", str(val))
    return float(found[0]) if found else None

# Cache table columns so we only insert valid keys
@functools.lru_cache(maxsize=64)
def fetch_columns(table: str):
    # Use SELECT * LIMIT 1 to infer columns from response keys
    data = sb_get(f"/rest/v1/{table}", params={"select":"*", "limit":"1"})
    if isinstance(data, list) and data:
        return set(data[0].keys())
    # Fallback to docs endpoint
    return set()

def sanitize(table: str, payload: dict):
    cols = fetch_columns(table)
    if not cols:
        # be permissive if we can't fetch schema, but log it
        log.warning("Schema unknown for table %s; inserting as-is", table)
        return payload
    return {k: v for k, v in payload.items() if k in cols}

# =========================
# User linking (Telegram → users.uuid)
# =========================
def ensure_user(telegram_id: str, full_name: str = None):
    # 1) try to find
    rows = sb_get("/rest/v1/users", params={"select":"id,telegram_id,full_name", "telegram_id":"eq."+str(telegram_id)})
    if isinstance(rows, list) and rows:
        return rows[0].get("id")

    # 2) create
    created = sb_post("/rest/v1/users", {
        "telegram_id": str(telegram_id),
        "full_name": full_name or ""
    })
    if isinstance(created, list) and created:
        return created[0].get("id")
    return None

# =========================
# OCR + Voice
# =========================
def extract_text_from_image(file_url: str) -> str:
    try:
        resp = requests.get(file_url, timeout=25)
        resp.raise_for_status()
        b64 = base64.b64encode(resp.content).decode("ascii")
        messages = [
            {"role": "system", "content": "Extract the exact readable text from this screenshot. No commentary."},
            {"role":"user","content":[
                {"type":"text","text":"Extract all readable text."},
                {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}
            ]}
        ]
        if openai_client:
            out = openai_client.chat.completions.create(
                model="gpt-4o-mini", messages=messages, max_tokens=1200, temperature=0
            )
            return out.choices[0].message.content.strip()
        else:
            out = openai.ChatCompletion.create(
                model="gpt-4o-mini", messages=messages, max_tokens=1200, temperature=0
            )
            return out.choices[0].message["content"].strip()
    except Exception as e:
        log.exception("OCR failed")
        return f"[OCR error] {e}"

def transcribe_voice(file_url: str) -> str:
    try:
        ogg = requests.get(file_url, timeout=30).content
        p_ogg, p_wav = "/tmp/v.ogg", "/tmp/v.wav"
        with open(p_ogg,"wb") as f: f.write(ogg)
        AudioSegment.from_ogg(p_ogg).export(p_wav, format="wav")
        rec = sr.Recognizer()
        with sr.AudioFile(p_wav) as src:
            audio = rec.record(src)
        return rec.recognize_google(audio)
    except Exception as e:
        log.exception("Voice transcription failed")
        return f"[Voice error] {e}"

# =========================
# Strict JSON Generator
# =========================
CONTAINER_FIELDS = {
    "sleep": [
        "date","sleep_score","energy_score","duration_hr","resting_hr","notes"
    ],
    "exercise": [
        "date","workout_name","distance_km","duration_min","calories_burned","training_intensity","avg_hr","notes"
    ],
    "food": [
        "date","meal_name","foodbank_item_id","calories","protein_g","carbs_g","fat_g","fiber_g","notes"
    ],
    "weight_history": [
        "weight_kg","recorded_at"
    ],
    "foodbank": [
        "name","calories","protein_g","carbs_g","fat_g","fiber_g","notes"
    ],
    "containers": [
        "name"
    ],
    "users": [
        "full_name","current_weight_kg","height_cm","goal_weight_kg","notes"
    ]
}

SYSTEM_JSON_PROMPT = (
    "You are a strict JSON generator for a health tracker. "
    "Given noisy text from screenshots or a short instruction, "
    "you must output ONLY a JSON object with: "
    "  container: one of [sleep, exercise, food, weight_history, foodbank, containers, users], "
    "  fields: an object ONLY with the allowed keys for that container (ignore everything else), "
    "  notes: optional brief text. "
    "Do not include keys you cannot infer. Do not invent values."
)

def allowed_for(container: str):
    return CONTAINER_FIELDS.get(container, [])

def call_openai_for_json(user_text: str):
    messages = [
        {"role":"system","content":SYSTEM_JSON_PROMPT},
        {"role":"user","content":user_text}
    ]
    try:
        if openai_client:
            resp = openai_client.chat.completions.create(
                model="gpt-4o-mini", messages=messages, max_tokens=400, temperature=0.1
            )
            raw = resp.choices[0].message.content.strip()
        else:
            resp = openai.ChatCompletion.create(
                model="gpt-4o-mini", messages=messages, max_tokens=400, temperature=0.1
            )
            raw = resp.choices[0].message["content"].strip()
        parsed = json.loads(raw)
    except Exception as e:
        log.warning("AI JSON parse error: %s", e)
        return str(e), None

    # prune unknown container/fields
    c = parsed.get("container")
    f = parsed.get("fields", {}) or {}
    if c not in CONTAINER_FIELDS:
        return raw, None
    whitelisted = {k: f.get(k) for k in allowed_for(c) if k in f}
    parsed["fields"] = whitelisted
    return raw, parsed

# =========================
# Mapping to DB payloads
# =========================
def with_date_default(fields: dict):
    d = fields.get("date")
    if not d:
        fields["date"] = now_iso()[:10]
    return fields

def payload_for(container: str, fields: dict, user_uuid: str):
    ts = now_iso()

    if container == "sleep":
        f = with_date_default(dict(fields))
        return "sleep", {
            "user_id": user_uuid,
            "date": f["date"],
            "sleep_score": clean_number(f.get("sleep_score")),
            "energy_score": clean_number(f.get("energy_score")),
            "duration_hr": clean_number(f.get("duration_hr")),
            "resting_hr": clean_number(f.get("resting_hr")),
            "notes": f.get("notes"),
            "created_at": ts, "recorded_at": ts
        }

    if container == "exercise":
        f = with_date_default(dict(fields))
        return "exercise", {
            "user_id": user_uuid,
            "date": f["date"],
            "workout_name": f.get("workout_name") or "Workout",
            "distance_km": clean_number(f.get("distance_km")),
            "duration_min": clean_number(f.get("duration_min")),
            "calories_burned": clean_number(f.get("calories_burned")),
            "training_intensity": clean_number(f.get("training_intensity")),
            "avg_hr": clean_number(f.get("avg_hr")),
            "notes": f.get("notes"),
            "created_at": ts, "recorded_at": ts
        }

    if container == "food":
        f = with_date_default(dict(fields))
        return "food", {
            "user_id": user_uuid,
            "date": f["date"],
            "meal_name": f.get("meal_name") or "Meal",
            "foodbank_item_id": clean_number(f.get("foodbank_item_id")),
            "calories": clean_number(f.get("calories")),
            "protein_g": clean_number(f.get("protein_g")),
            "carbs_g": clean_number(f.get("carbs_g")),
            "fat_g": clean_number(f.get("fat_g")),
            "fiber_g": clean_number(f.get("fiber_g")),
            "notes": f.get("notes"),
            "created_at": ts, "recorded_at": ts
        }

    if container == "weight_history":
        return "weight_history", {
            "user_id": user_uuid,
            "weight_kg": clean_number(fields.get("weight_kg")),
            "recorded_at": fields.get("recorded_at") or ts
        }

    if container == "foodbank":
        return "foodbank", {
            "user_id": user_uuid,
            "name": fields.get("name"),
            "calories": clean_number(fields.get("calories")),
            "protein_g": clean_number(fields.get("protein_g")),
            "carbs_g": clean_number(fields.get("carbs_g")),
            "fat_g": clean_number(fields.get("fat_g")),
            "fiber_g": clean_number(fields.get("fiber_g")),
            "notes": fields.get("notes"),
            "created_at": ts
        }

    if container == "containers":
        return "containers", {
            "user_id": user_uuid,
            "name": fields.get("name"),
            "created_at": ts
        }

    if container == "users":
        # Updatable user fields via PATCH
        payload = {}
        if fields.get("full_name"): payload["full_name"] = fields["full_name"]
        # You can add height/goal/current weight if you add those columns later
        return "users", payload

    return None, None

# =========================
# Router to Supabase
# =========================
def route_to_supabase(parsed, chat_id, full_name=None):
    if not parsed or "container" not in parsed:
        return False, "no_container", {}

    # link user
    user_uuid = ensure_user(str(chat_id), full_name)  # may be None if users table is locked, but we'll proceed

    container = parsed["container"]
    fields = parsed.get("fields", {}) or {}
    table, payload = payload_for(container, fields, user_uuid)

    if not table or payload is None:
        return False, "map_failed", {}

    # if users payload is empty (no updates), nothing to do
    if container == "users":
        if not payload:
            return True, "noop_user", {}
        ok = sb_patch(f"/rest/v1/users?telegram_id=eq.{chat_id}", payload)
        return (ok is not None), ("user_updated" if ok else "user_update_failed"), payload

    sanitized = sanitize(table, payload)
    if not sanitized:
        return False, "empty_payload", {}

    res = sb_post(f"/rest/v1/{table}", sanitized)
    if res is None:
        return False, "insert_failed", sanitized
    return True, "insert_ok", sanitized

# =========================
# entries audit log
# =========================
def log_entry(chat_id, text, ai_text, parsed, status):
    _ = sb_post("/rest/v1/entries", {
        "chat_id": str(chat_id),
        "user_message": text,
        "ai_response": ai_text,
        "parsed": bool(parsed),
        "parsed_json": parsed,
        "created_at": now_iso()
    })

# =========================
# Telegram reply
# =========================
def send_tg(chat_id, text):
    try:
        requests.post(f"{TG}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception:
        log.exception("Telegram send failed")

# =========================
# Flask endpoints
# =========================
@app.route("/")
def index():
    return jsonify({"status":"ok"})

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True) or {}
    msg = data.get("message") or data.get("edited_message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    full_name = (chat.get("first_name","") + " " + chat.get("last_name","")).strip()

    text = ""
    if "photo" in msg:
        fid = msg["photo"][-1]["file_id"]
        f = requests.get(f"{TG}/getFile?file_id={fid}", timeout=15).json()
        path = f.get("result",{}).get("file_path")
        text = extract_text_from_image(f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{path}") if path else "[OCR error]"
    elif "voice" in msg:
        fid = msg["voice"]["file_id"]
        f = requests.get(f"{TG}/getFile?file_id={fid}", timeout=15).json()
        path = f.get("result",{}).get("file_path")
        text = transcribe_voice(f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{path}") if path else "[Voice error]"
    else:
        text = msg.get("text","")

    ai_text, parsed = call_openai_for_json(text)
    ok, status, payload = route_to_supabase(parsed, chat_id, full_name=full_name)
    log_entry(chat_id, text, ai_text, parsed, status)

    # Minimal echo: only the fields that matter for the chosen container
    preview = (text[:400] + "…") if len(text) > 400 else text
    lines = [f"OCR/Transcript preview:\n{preview}\n",]
    if parsed and parsed.get("container"):
        lines.append(f"📦 Container: {parsed['container']}")
        if payload:
            pretty = "\n".join([f"{k}: {v}" for k,v in payload.items() if v not in (None,"")])
            if pretty:
                lines.append(pretty)
    lines.append("\n✅ Logged successfully." if ok else f"\n⚠️ Insert failed: {status}")
    if parsed and parsed.get("notes"):
        lines.append(f"Notes: {parsed['notes']}")
    send_tg(chat_id, "\n".join(lines))

    return jsonify({"ok": True})

# =========================
# Run
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))