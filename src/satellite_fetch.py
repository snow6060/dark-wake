import os
os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")

from pystac_client import Client
from supabase import create_client
import rasterio
from PIL import Image

def run_fetch_cycle(settings, client):
    zones = settings.load_active_zones()
    for z in zones:
        process_zone(z, settings, client)

def process_zone(zone, settings, client):
    search = client.search(
        collections=["sentinel-2-l2a"],
        bbox=zone["bbox"],
        datetime=zone.get("date_range")
    )
    for item in search.items():
        with rasterio.open(item.assets["thumbnail"].href) as src:
            arr = src.read(1)
        cloud_pct = float((arr > 0).mean())
        valid_pct = 100.0 - cloud_pct
        img = Image.fromarray(arr)
        img.save("/tmp/snap.jpg")
        supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
        supabase.storage.from_("satellite-snapshots").upload("snap.jpg", "/tmp/snap.jpg")
