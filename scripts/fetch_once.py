#!/usr/bin/env python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.satellite_fetch import run_fetch_cycle
from src.spatial_config import SpatialSettings

def main():
    settings = SpatialSettings()
    from pystac_client import Client
    client = Client.open("https://earth-search.aws.element84.com/stac")
    run_fetch_cycle(settings, client)

if __name__ == "__main__":
    main()
