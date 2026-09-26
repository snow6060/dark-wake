# DarkWake

Multi-agent oil-market intelligence tool built on top of an existing Brent
crude trading script. DarkWake tracks live chokepoint traffic (Bab-el-Mandeb,
Strait of Hormuz, and more later) and will eventually layer AI agents on top
for analysis, plus AIS-based dark-vessel detection.

This is a phased build. See `docs/` (added in later phases) for phase
summaries.

## Phase 1 — Foundation & chokepoint data ingestion

Scope of this phase:
- Repo scaffold
- Ingestion from the IMF PortWatch `Daily_Chokepoints_Data` FeatureServer
- SQLite storage with an idempotent upsert and a computed
  deviation-from-baseline field
- An hourly APScheduler job
- A minimal FastAPI endpoint serving the stored time series
- A sanity-check plotting script

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .          # installs the darkwake package (src/ layout) in editable mode
cp .env.example .env
```

## Usage

Run a one-off ingest:

```bash
python -m darkwake.ingest.portwatch
```

Run the scheduler (ingests immediately, then every `INGEST_INTERVAL_HOURS`):

```bash
python -m darkwake.scheduler
```

Run the API:

```bash
uvicorn darkwake.api.main:app --reload
```

Then:

```bash
curl "http://localhost:8000/chokepoints/hormuz/timeseries?days=90"
```

Sanity-check plot:

```bash
python scripts/plot_chokepoint.py hormuz
```

## License

MIT
