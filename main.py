#!/usr/bin/env python3
import os, json, logging, requests, base64, re, functools
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
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return val
    try:
        n = re.findall(r"[-+]?\d*\.\d+|\d+", str(val))
        return float(n[0]) if n else None
    except Exception:
        return None

# -------------------------------------------------------
# Schema definitions (strict)
# -------------------------------------------------------
SCHEMA = {
    "sleep": {
        "sleep_score": float,
        "energy_score": float,
        "duration_hr": float,
        "resting_hr": float,
        "notes": str
    },
    "food": {
        "meal_name": str,
        "calories": float,
        "protein_g": float,
        "carbs_g": float,
        "fat_g": float,
        "fiber_g": float,
        "notes": str
    },
    "exercise": {
        "workout_name": str,
        "distance_km": float,
        "duration_min": float,
        "calories_burned": float,
        "training_intensity": float,
        "avg_hr": float,
        "notes": str
    }
}

@functools.lru_cache(maxsize=64)
def fetch_table_columns(table: str):
    return list(SCHEMA.get(table, {}).keys())

def sanitize_payload(payload, table):
    valid = set(fetch_table_columns(table))
    return {k: v for k, v in payload.items() if k in valid and v not in (None, "", "null")}

def sb_post(path, payload):
    try:
        r = requests.post(f"{SUPABASE_URL}{path}", headers=sb_headers(), json=payload, timeout=15)
        if r.status_code not in (200, 201):
            logger.error("Supabase insert failed %s %s", r.status_code, r.text)
            return False
        return True
    except Exception as e:
        logger.error("Supabase POST error