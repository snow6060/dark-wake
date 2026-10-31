import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from src.analysis_run import analyze_latest  # noqa: E402
from src.job_reporter import Reporter  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--zone", required=True)
ap.add_argument("--ais-json")
ap.add_argument("--image")
ap.add_argument("--no-write", action="store_true")
a = ap.parse_args()
rep = Reporter()
summary = analyze_latest(a.zone, rep, a.ais_json, a.image, write=not a.no_write)
rep.finish()
print(json.dumps(summary, indent=2))