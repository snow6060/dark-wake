import os
from dotenv import load_dotenv
import httpx
from supabase import create_client, Client
from supabase.lib.client_options import SyncClientOptions

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = None

if SUPABASE_URL and SUPABASE_KEY:
    try:
        rest_client = httpx.Client(http2=False, timeout=120)
        supabase = create_client(
            SUPABASE_URL,
            SUPABASE_KEY,
            options=SyncClientOptions(httpx_client=rest_client),
        )
        print("[Supabase] Connected successfully.")
    except Exception as e:
        print(f"[Supabase Warning] Failed to initialize client: {e}")
else:
    print("[Supabase Warning] Credentials not found; using local storage only.")
