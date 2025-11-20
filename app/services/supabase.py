import os
from supabase import create_client, Client

# ================================
# INIT SUPABASE CLIENT
# ================================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


# ================================
# CORE INSERT FOR CONTAINERS
# ================================
def insert_record(table: str, data: dict):
    """
    Insert one row into Supabase.
    Returns:
        (response, error_str)
    """
    try:
        response = supabase.table(table).insert(data).execute()
        return response, None
    except Exception as e:
        print(f"[SUPABASE ERROR {table}]", e)
        return None, str(e)


# ================================
# SHADOW LOGGING — entries table
# ================================
def log_entry(
    chat_id: str,
    raw_text: str,
    parsed: dict | None = None,
    container: str | None = None,
    error: str | None = None,
):
    """
    Log ANY message for debugging/auditing/classifier training.
    This MUST NEVER interrupt the main pipeline.
    """
    payload = {
        "chat_id": chat_id,
        "raw_text": raw_text,
        "parsed": parsed,
        "container": container,
        "error": error,
    }

    try:
        supabase.table("entries").insert(payload).execute()
        print("[ENTRIES LOGGED]", payload)
    except Exception as e:
        print("[SUPABASE ERROR entries]", e)
