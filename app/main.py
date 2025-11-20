import os
from flask import Flask
from supabase import create_client, Client
from openai import OpenAI
import pytz

# ================================
# IMPORT BLUEPRINT
# ================================
from app.api.webhook import api

# ================================
# INIT
# ================================
app = Flask(__name__)
app.register_blueprint(api)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GPT_PROMPT_ID = os.getenv("GPT_PROMPT_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

UTC = pytz.UTC


# ================================
# START
# ================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
