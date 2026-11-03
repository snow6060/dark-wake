# Dark Wake

Dark Wake is a local maritime and energy intelligence prototype. It brings
market context, shipping data, satellite imagery, and structured debate into
one dashboard so analysts can see what is known, what may matter, and where
important evidence is still missing.

The hackathon version is on the
[`meta-hackathon-upgrade` branch](https://github.com/snow6060/dark-wake/tree/meta-hackathon-upgrade).
Its full development history is preserved there. This project runs locally;
it is not a hosted or real-time surveillance service.

## What the app does

### Overview

The first tab is the operating overview: Brent market data, energy headlines,
and maritime chokepoint context appear together. It is intended as a fast
orientation layer—not a substitute for primary market, shipping, or government
sources. Market quotes depend on Yahoo Finance being reachable and may be
unavailable or delayed.

### Strategy Desk

The Strategy Desk follows a debate-and-risk-review process inspired by a
commodity trading desk:

1. A technical analyst reviews the available prices and indicators.
2. A supply-focused bull and a demand-focused bear each make a case.
3. The supply and demand analysts rebut each other over two rounds.
4. A separate risk-synthesis agent weighs the evidence and issues the final
   BUY, SELL, or HOLD view, confidence, rationale, and risk factors.

The synthesis is a model-generated research opinion, not investment advice or
a trade instruction. It should disclose stale or missing inputs; when a live
Brent quote is unavailable, the dashboard quote is passed to the debate if
available, otherwise the app may use a clearly labelled previously saved
price.

### Spatial Intelligence

The goal of Spatial Intelligence is to surface maritime anomalies by comparing
what ships report over AIS with what can be seen in satellite imagery. The
intended intelligence use includes investigating vessels that go dark,
positions or movement that do not agree with visual evidence, possible AIS
spoofing, and vessels that may warrant a check against sanctions lists.

**Those goals are not fully achieved in this prototype.** The app can retrieve
Sentinel-2 optical scenes, propose visible vessel candidates, compare them
with timestamp-matched AIS history, and show unmatched or displaced results.
The imagery is periodic—not a continuous live satellite feed—and AIS history
coverage and timestamps can be limited. At 10 m per pixel, an image detection
is evidence to review, not vessel identity.

In particular, Dark Wake does **not** currently confirm sanctions status,
prove AIS spoofing, establish why a vessel is not matched, or verify cargo or
ship-to-ship transfer. An unmatched detection is an anomaly lead, not proof of
wrongdoing. Operational maritime intelligence would require frequent,
well-timed imagery; dependable AIS coverage; validated vessel identity and
sanctions/watchlist sources; and human review.

The value of that direction is earlier, more explainable review of possible
shipping and supply-chain disruptions. Combining independent sources can help
analysts prioritize what to investigate instead of treating one feed as the
whole picture. The current build is a demonstration of that workflow and its
limitations, not a live enforcement or navigation system.

## Install and configure

### Requirements

- Windows 10/11 and PowerShell
- Python 3.12
- Node.js 22 LTS (includes npm)
- A Supabase project
- Provider credentials for the services you intend to use

### 1. Set up Supabase

For a **new Supabase project**, open the Supabase SQL Editor and run
[`sql/supabase_setup.sql`](./sql/supabase_setup.sql). It creates the tables
used by the app, including the spatial zones and snapshots, analysis results,
market/news context, and Strategy Desk history and memory.

This is an initial schema for a new project, not a migration for a database
that already contains production data. Back up an existing database and
prepare a migration before applying schema changes to it.

Create a **public** Storage bucket named `satellite-snapshots` in Supabase
Storage. The frontend displays stored satellite images through their public
URLs. Do not store credentials in the bucket or in frontend code.

The SQL creates the zone table but does not insert zone records. After starting
the app, use Spatial Intelligence's **Add Zone** control to define the maritime
areas you want to analyze. A zone needs a bounding box and must be active.

### 2. Configure and install the backend

From the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit `.env` and add the credentials you need:

| Variable | Purpose |
| --- | --- |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase **service-role** key used by the local backend; never put it in frontend variables or commit it |
| `VOYAGE_RADAR_API_KEY` | Historical AIS data for spatial analysis |
| `META_MODEL_API_KEY` | Strategy Desk model responses |
| `HF_TOKEN` | Optional model download token when SAM refinement is enabled |

`AIS_API_BASE` and the model settings have defaults in `.env.example`.
To skip optional SAM refinement, set `SAM_ENABLE=0` in `.env`. The classical
vessel-proposal pipeline can still run, but remains experimental.

### 3. Start the backend

With the virtual environment active, from the repository root:

```powershell
uvicorn main:app --reload
```

The API is at <http://localhost:8000>; interactive documentation is at
<http://localhost:8000/docs>.

### 4. Start the frontend

Open a second PowerShell terminal:

```powershell
Set-Location .\dark-wake
npm ci
npm run dev
```

Open the local address printed by Vite, usually <http://localhost:5173>. The
frontend uses `http://localhost:8000` by default. If your backend is at a
different address, set `VITE_API_BASE_URL` in `dark-wake/.env.local`.

The optional Tauri desktop shell can also be run locally. Install Rust and the
platform's native build tools, then run `npm run tauri dev` from `dark-wake`.

## Data and limitations

- The first spatial fetch may take time: imagery must be found and downloaded,
  and optional model weights may need to be fetched. Job progress is shown in
  the app.
- Sentinel-2 scenes are periodic and are not a live satellite stream. The
  stored capture time, AIS query window, cloud cover, and coverage affect what
  can be compared.
- A water mask limits candidate detections to likely water pixels, but does
  not eliminate every image-classification error.
- Historical AIS results depend on the provider's coverage and available
  query windows. A missing match does not establish spoofing or sanctions.
- Data providers can be unavailable, rate-limited, delayed, or return
  incomplete results. The app should show those limitations rather than
  treating missing values as zero.
- This software is for demonstration and research. It is not for navigation,
  enforcement decisions, or financial advice.

## License

See [LICENSE](./LICENSE).
