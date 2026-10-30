#!/usr/bin/env python
"""Fetch real Sentinel-2 captures for the Spatial Intelligence zones, once.

Examples (run from the repository root, venv active):
  python scripts/fetch_once.py --zone fujairah --dry-run          # look only: STAC + cloud check
  python scripts/fetch_once.py --zone fujairah --dry-run --local-dir _private/out
                                                                  # also save JPEGs to eyeball framing
  python scripts/fetch_once.py --zone fujairah                    # upload + record in Supabase
  python scripts/fetch_once.py                                    # all active zones
"""
import argparse
import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from src.satellite_fetch import run_fetch_cycle  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--zone", action="append", help="zone_id to fetch (repeatable); default: all active zones")
    parser.add_argument("--dry-run", action="store_true", help="do not upload or write to the database")
    parser.add_argument("--local-dir", help="also save the JPEGs into this folder (use a git-ignored path)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    results = run_fetch_cycle(zone_ids=args.zone, dry_run=args.dry_run, local_dir=args.local_dir)
    print(json.dumps(results, indent=2, default=str))
    return 1 if any(r.get("status") == "error" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
