"""Quick sanity-check plot: last N days of a chokepoint's daily transits,
read straight from local storage (no API server required).

Usage:
    python scripts/plot_chokepoint.py hormuz
    python scripts/plot_chokepoint.py bab_el_mandeb --days 60
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

import matplotlib.pyplot as plt
from sqlalchemy import select

from darkwake.config import settings
from darkwake.db import ChokepointTransit, SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chokepoint", choices=sorted(settings.chokepoints.keys()))
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--out", default=None, help="Output PNG path (defaults to <chokepoint>.png)")
    args = parser.parse_args()

    cutoff = dt.date.today() - dt.timedelta(days=args.days)
    with SessionLocal() as session:
        records = (
            session.execute(
                select(ChokepointTransit)
                .where(
                    ChokepointTransit.chokepoint_key == args.chokepoint,
                    ChokepointTransit.date >= cutoff,
                )
                .order_by(ChokepointTransit.date.asc())
            )
            .scalars()
            .all()
        )

    if not records:
        print(
            f"No rows found for '{args.chokepoint}' in the last {args.days} days. "
            "Run the ingest first: python -m darkwake.ingest.portwatch",
            file=sys.stderr,
        )
        sys.exit(1)

    dates = [r.date for r in records]
    totals = [r.n_total for r in records]
    baselines = [r.baseline_n_total for r in records]

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(dates, totals, label="Daily total transits", marker="o", markersize=3)
    ax.plot(dates, baselines, label="Trailing baseline", linestyle="--")
    ax.set_title(f"{records[0].portname} — last {args.days} days")
    ax.set_xlabel("Date")
    ax.set_ylabel("Vessel transits")
    ax.legend()
    fig.autofmt_xdate()

    out_path = args.out or f"{args.chokepoint}.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved {out_path} ({len(records)} rows)")


if __name__ == "__main__":
    main()
