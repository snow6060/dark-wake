import os
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = None

if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("✅ Connected to Supabase successfully.")
    except Exception as e:
        print(f"⚠️ Failed to initialize Supabase client: {e}")
else:
    print("⚠️ Supabase URL or Key not found in environment variables. Running in local fallback mode.")