# Dark Wake

Dark Wake is a locally run maritime and energy intelligence app. It combines a
React dashboard with a FastAPI backend for market data, news, satellite imagery,
vessel detection, and AIS history.

The supported setup runs the frontend and backend on your own computer. This
repository does not include Docker deployment or hosted release workflows.
Hackathon development and its full commit history are preserved on the
[`meta-hackathon-upgrade` branch](https://github.com/snow6060/dark-wake/tree/meta-hackathon-upgrade).

## Requirements

- Windows 10/11 with PowerShell
- Python 3.12
- Node.js 22 LTS (npm is included)
- A Supabase project and provider credentials for the features you want to use

## Configure the backend

Open a terminal at the repository root and create a virtual environment:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit `.env` in the repository root. Add the credentials for the integrations
you plan to use:

| Variable | Used for |
| --- | --- |
| `SUPABASE_URL`, `SUPABASE_KEY` | Spatial zones, saved satellite captures, and analysis data. Keep the service-role key on the backend only. |
| `VOYAGE_RADAR_API_KEY` | Historical AIS vessel data used by spatial analysis. |
| `META_MODEL_API_KEY` | Strategy Desk debates. |
| `HF_TOKEN` | Downloading the SAM model when SAM analysis is enabled. |

`AIS_API_BASE` and the model settings have defaults in `.env.example`. The
dashboard connects to `http://localhost:8000` by default; set
`VITE_API_BASE_URL` in `dark-wake/.env.local` only if you need a different
local backend address.

For spatial analysis, provision the `spatial_zones`, `spatial_snapshots`,
`spatial_analysis`, and `spatial_startup_state` tables, populate the active
zones, and configure the Supabase Storage bucket.
[`spatial_analysis.sql`](./sql/spatial_analysis.sql) creates or updates the
analysis table; the other tables and bucket must also be set up in your
Supabase project.
Never put backend credentials in frontend environment variables or commit a
real `.env` file.

## Start the app

### 1. Start the backend

In the activated virtual environment, from the repository root:

```powershell
uvicorn main:app --reload
```

The API runs at <http://localhost:8000>; its interactive documentation is at
<http://localhost:8000/docs>.

### 2. Start the frontend

Open a second terminal:

```powershell
Set-Location .\dark-wake
npm ci
npm run dev
```

Open the local URL printed by Vite, usually <http://localhost:5173>.

The optional Tauri desktop shell can also be run locally. Install Rust and the
platform's native build tools, then run `npm run tauri dev` from `dark-wake`.

## Notes

- The first spatial run may take longer while satellite imagery and model
  weights download. The app displays job progress while it fetches imagery,
  retrieves timestamp-matched AIS history, and analyzes the selected zones.
- The Strait of Hormuz zone is hidden from the selectable dashboard list; the
  other four preset zones remain available.
- The frontend can be production-built locally with `npm run build` from
  `dark-wake`.
- This project calls external data and model providers when their features are
  used; running the app locally does not make those services run offline.

## License

See [LICENSE](./LICENSE).
