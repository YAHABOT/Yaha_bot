import os
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

# Create the Supabase client once
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def insert_record(table: str, data: dict):
    """
    Inserts a record into a Supabase table.
    This wraps the old inline logic from main.py.
    """
    try:
        response = supabase.table(table).insert(data).execute()
        return response, None
    except Exception as e:
        return None, e

