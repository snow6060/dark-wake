# Dark Wake — Application Description and Technical Guide

## 1. What Dark Wake is

Dark Wake is a desktop energy-market and maritime supply-chain intelligence application. It brings together an energy commodity basket, commercial energy headlines, daily maritime-transit counts at major routes, historical telemetry, and a multi-agent analysis of global energy markets.

The app is designed to make those research inputs available in one place without asking an ordinary user to install Python, run a backend, configure API credentials, create a database, or understand the data-ingestion pipeline. The Windows desktop app is a lightweight client. It connects to a separately hosted backend over HTTPS; the backend gathers and prepares the data and serves it to the client.

Dark Wake is an **information and research aid**, not a trading system, brokerage, price feed guarantee, or investment adviser. Its indicators, estimates, sourced data, and AI-generated analysis can be delayed, incomplete, inaccurate, or affected by provider outages. It does not execute trades.

## 2. Intended use

Oil prices can react to several kinds of information at once:

- Changes in the price and short-term direction of Brent crude.
- Supply risks and shipping activity near major oil chokepoints.
- Commercial news about energy, supply, shipping, trade, and demand.
- Technical market conditions such as moving averages, momentum, and recent price ranges.
- Competing interpretations of the available evidence.

Dark Wake places these inputs side by side. A user can review source data and headlines first, then open the Strategy Desk to see a structured technical, supply, demand, and risk-synthesis analysis. The goal is to help organize research and expose competing arguments—not to replace independent judgement or primary-source verification.

## 3. The end-user experience

### 3.1 What users download

The Windows release is distributed as a Tauri NSIS setup executable. At the time of writing, the release build is about 1.4 MiB. Users download the installer, run it, and open Dark Wake from the installed application/Start menu.

The desktop app bundles its user interface. It does **not** bundle the Python backend, database, Meta Model API key, or Supabase secret. It uses the configured hosted backend URL, currently:

```text
https://dark-wake-backend.onrender.com
```

### 3.2 What users do not need to configure

For the normal distributed desktop experience, an end user does not need to:

- Install Python or Node.js.
- Start a terminal, local API server, or background scheduler.
- Install or configure SQLite, Supabase, or another database.
- Create a Meta Model API account or provide a model API key.
- Configure TankerMap, Straits.live, PortWatch, Yahoo Finance, or RSS credentials.
- Run data scraping or market-analysis scripts.

Those responsibilities belong to the hosted backend and its operator. The desktop app makes HTTPS API requests and renders the returned data.

### 3.3 Availability and cost caveat

The desktop installer can be offered as a free download, and ordinary users do not need their own provider keys. That does not guarantee that every backend or upstream service will always be free, available, or unlimited. Availability depends on the current hosting plan, host sleep/restart behavior, external data sources, Supabase configuration, and Meta Model API quotas or billing terms. A free hosting instance may sleep when idle; the first request after sleep can be slow, and scheduled server jobs cannot run while the service is stopped or asleep.

The app has no offline data mode. If the hosted backend or network is unavailable, existing screen defaults may remain visible, but fresh data and Strategy Desk history cannot be relied on until the API responds.

## 4. Application layout

The interface has two top-level tabs:

1. **News & Price** — market price, headlines, daily chokepoint traffic, and historical telemetry.
2. **Energy Strategy Desk** — the latest saved analysis, its multi-agent transcript, and the final desk signal and risk synthesis.

The app is a desktop shell around a React interface built with Vite and packaged using Tauri 2. Its backend is a FastAPI Python service.

## 5. Tab One: News & Price

### 5.1 Summary cards

The top row summarizes several data points:

- **BrentCash (BZ=F):** a Brent futures price response obtained from Yahoo Finance through the backend. The displayed percentage is calculated from the returned history for the request.
- **Strait of Hormuz Traffic:** the latest available daily tanker-transit count for the Strait of Hormuz, with its date and selected source.
- **Bab el-Mandeb Traffic:** the same daily-transit presentation for Bab el-Mandeb. A live in-zone snapshot does not replace this daily figure in the card.
- **News Sources:** a summary label for the configured headline sources.
- **System Status:** a presentation label in the interface. It should not be treated as a separate continuous end-to-end health probe; the backend's `/health` endpoint is the API health check.

The daily transit card format is:

```text
<count> tankers/day
<source> data as of <date>
Source: <source> daily tanker transits
```

If no daily record is available, the card reports that data is unavailable rather than deriving a count from unrelated data.

### 5.2 Brent price chart

The price panel displays a line chart built from the market-price endpoint's recent history. The backend requests Yahoo Finance `BZ=F` data using a five-minute interval for the current day and falls back to a broader recent history if that series is empty. The response contains up to the most recent twelve observations for the chart.

This is a convenience view of a third-party data response. It is not a guaranteed real-time exchange feed. Yahoo Finance may return no history or an error; the current backend has fallback display values for some failure/empty-data cases, so users should verify a price independently before relying on it.

### 5.3 Commercial energy news

The news panel shows the latest returned articles, with a compact list and a **View All** dialog for the available response items. Article entries can include:

- Headline and source name.
- Publication or stored timestamp.
- Link to the publisher's original article.
- A simple sentiment label.
- A summary when the upstream feed and database schema provide one.

Configured RSS publishers currently include OilPrice Energy News, CNBC Energy, and EIA Today in Energy. The backend also parses headlines from TankerMap's public news page. The frontend sorts returned entries by publication/stored time and displays up to ten in the main panel.

RSS sentiment is a lightweight keyword heuristic, not a financial NLP model or a verified assessment of an article's full context. TankerMap items may have a neutral label. Headlines and article text belong to their original publishers; follow the link and review the full source when accuracy or context matters.

### 5.4 Chokepoint Traffic Telemetry chart

The telemetry section lets a user switch between:

- Strait of Hormuz.
- Bab el-Mandeb.

It summarizes and plots daily tanker transits, including the latest daily count and a recent seven-record daily average. The chart displays up to the most recent 90 returned days; a **View Full Chart** control opens the full available history.

When the selected source is TankerMap, the chart is described as daily AIS tanker transits. When the selected source is IMF PortWatch, PortWatch provides daily vessel counts and its tanker-capacity-based estimated oil-flow series may be shown separately. TankerMap's public daily transit series does not provide a directly comparable oil-flow estimate, so Dark Wake does not invent one or combine it with PortWatch to imply comparability.

### 5.5 What “daily” and “live” mean here

The traffic cards and chart use **daily transit records**. Those values are not counts of all ships physically in the area at the moment a user opens the app.

The backend also fetches vessel snapshots:

- Straits.live supplies a recent aggregate observation for Hormuz.
- TankerMap's public page can provide a recent Bab el-Mandeb in-zone snapshot.

The `/api/chokepoints` response includes these snapshots, their source, observation time, and a freshness flag. The traffic cards intentionally display daily transits consistently rather than changing format depending on whether an in-zone snapshot happens to be fresh. The app does not provide an individual-vessel map or live vessel-position tracking interface.

## 6. Tab Two: Energy Strategy Desk

### 6.1 Purpose

The Strategy Desk is a structured energy-market analysis. Instead of presenting one unchallenged model opinion, it asks different analytical roles to examine a shared market snapshot and produce a final synthesis. The sequence is intended to make assumptions and counterarguments easier to inspect.

The Strategy Desk uses the configured Meta Model API model for each role, with distinct role instructions and sequential context. The model is instructed to use the supplied data, acknowledge unavailable indicators, and avoid inventing facts.

### 6.2 Inputs gathered for a run

Before the agents run, the backend gathers a snapshot that may include:

- Daily market data and technical indicators for Brent, WTI, natural gas, heating oil, gasoline, and coal from Yahoo Finance.
- Recent market data from Supabase if configured and available.
- Local daily TankerMap chokepoint records, preferring them when their latest date is at least as recent as cloud telemetry; otherwise it can use available Supabase telemetry or local PortWatch records.
- Recent headlines saved in Supabase.
- Quantitative technical indicators computed from each available commodity's daily OHLCV history.
- A concise summary of the previous saved analysis and agent-accuracy feedback, when available.
- A capture timestamp and source labels.

The agents should treat the newly gathered context as authoritative for the current run and use the previous debate only as comparison context. A data-source failure can mean that an input is unavailable or that a particular retrieval path falls back; the model's output is only as sound as the inputs it receives.

When the market is closed for the weekend, every role is explicitly told that its supplied price is the last available close, not a live weekend quote, and to base its assessment on that close alongside available news and other context. When Yahoo Finance has no intraday quote on a weekday, agents are likewise told not to present the daily fallback as current intraday pricing. The interface labels close-based analysis prices as **LAST CLOSE** and shows the close timestamp for weekend analyses.

### 6.3 Debate sequence

The LangGraph workflow executes eight model stages sequentially:

1. **Gather context:** prepare market, telemetry, headlines, technical report, and prior-debate context.
2. **Technical Analysis:** assess the provided RSI, MACD, EMA, Bollinger Bands, ATR, stochastic, and VWAP values, and identify unavailable values without inventing them.
3. **Supply Thesis:** develop an evidence-led view of energy availability, inventories, production, and commercial shipping.
4. **Demand Thesis:** assess consumption, trade, and alternative interpretations of the shared evidence.
5. **Supply Rebuttal 1:** respond to the demand thesis with specific counter-evidence.
6. **Demand Rebuttal 1:** respond to the supply thesis.
7. **Supply Rebuttal 2** and **Demand Rebuttal 2:** complete the second and final rebuttal loop.
8. **Desk Signal & Risk Synthesis:** reconcile the technical data and all thesis turns into a validated `BUY`, `SELL`, or `HOLD` signal.

Calls use the configured Meta Model API model and can fall back to supported model IDs when the configured model is unavailable. Requests are retried for selected transient failures. A malformed final synthesis receives one JSON-format repair attempt and is validated before saving. Tests mock all model requests; live API calls are not part of the unit-test suite.

### 6.4 What the Strategy Desk displays

The interface presents:

- The latest saved analysis and its last-run time, formatted in Europe/London time. Closing-price analyses are labeled **LAST CLOSE**, and weekend runs show the close date.
- A transcript of the Technical Analysis, Supply Thesis, Demand Thesis, and four rebuttal stages.
- The final Desk Signal & Risk Synthesis as an executive summary.
- A final `BUY`, `SELL`, or `HOLD` desk signal and conviction score.
- Short-term and long-term direction labels.
- Support and resistance levels.
- Optional entry, stop-loss, and take-profit values when supplied.
- Risk factors and data-source labels.
- A short history list when multiple saved debates are available.

The final signal is an analytical output, not a command to trade. Conviction is a model-generated score, not a probability guarantee or measured success rate. Price levels and forecasts are not assured outcomes.

### 6.5 Automatic execution and loading behavior

The backend scheduler is configured to run the analysis once daily at **08:00 Europe/London time** (the timezone database applies GMT/BST changes). It also checks that a recent run is not regenerated unnecessarily: a saved analysis less than 24 hours old is reused.

When the user opens the Strategy Desk, the frontend requests saved analysis history only; reading the history does not start an analysis. This lets the latest saved run appear without waiting for AI generation. The backend scheduler checks for a due run at 08:00 Europe/London, and `run_debate_if_due()` reuses an analysis less than 24 hours old. Explicit analysis endpoints may also request a run, subject to that same 24-hour check.

If a scheduled refresh fails (for example, because market data or an AI provider is temporarily unavailable), previously saved analyses remain available in history. Loading the Strategy Desk only reads those saved results; it does not block on an AI refresh.

If the hosted backend is asleep, its scheduled jobs are paused. A request may wake the service, but this does not mean the scheduler ran continuously while asleep. The Strategy Desk also requires its server-side Meta Model API and Supabase configuration; end users do not supply those credentials.

## 7. Data collection and refresh pipeline

### 7.1 Overall flow

```text
Public/provider data sources
          |
          v
Hosted FastAPI service + background scheduler
          |
          +--> SQLite on the backend for local telemetry
          +--> Supabase for saved news, debates, and cloud telemetry sync
          |
          v
HTTPS JSON API
          |
          v
React/Tauri desktop client on each user's computer
```

The desktop application does not scrape upstream sites directly and does not contain service credentials. The backend fetches and normalizes data, while the client requests API responses and renders them.

### 7.2 Backend startup tasks

At FastAPI startup the service:

1. Creates or migrates its SQLite tables.
2. Requests an initial IMF PortWatch refresh.
3. Requests an initial Straits.live Hormuz snapshot.
4. Requests TankerMap chokepoint pages and stores their daily transit series and Bab el-Mandeb live snapshot.
5. Fetches RSS feeds if Supabase is configured.
6. Starts APScheduler in the backend process.

External requests can fail independently. The ingestion functions generally log source-specific errors and preserve previously stored data where implemented. A successful API process startup does not prove that every external source returned fresh data.

### 7.3 Scheduled refresh intervals

The current scheduler is configured as follows:

| Job | Configured interval |
| --- | --- |
| IMF PortWatch daily chokepoint telemetry | Every hour |
| TankerMap daily transit series and Bab el-Mandeb snapshot | Every hour, with an early run shortly after startup |
| Straits.live Hormuz snapshot | Every five minutes, with an early run shortly after startup |
| RSS headline collection to Supabase | Every 60 seconds |
| Strategy Desk check/run | Once daily at 08:00 Europe/London |

Actual freshness depends on the backend process being awake, the job succeeding, the upstream source being current, and any platform limits. “Live” in the interface/API describes recent retrieval from a source, not a guaranteed real-time feed or continuous 24/7 operation.

### 7.4 Desktop API polling

While the app is open, the React client requests:

- `/api/market/prices`
- `/api/news/feed`
- `/api/chokepoints`

These are polled every 15 seconds. This refreshes the displayed response; it does not force every upstream dataset to be re-ingested every 15 seconds. Most underlying sources are refreshed by the backend scheduler at their own intervals. The price endpoint makes its Yahoo Finance request when queried.

When the user changes to the Strategy Desk tab, the client requests `/api/strategy-desk/debates`. Loading saved analyses can cause the backend due-check described above.

## 8. Data sources and interpretation

### 8.1 Yahoo Finance

Yahoo Finance is queried by the backend for the energy commodity basket (`BZ=F`, `CL=F`, `NG=F`, `HO=F`, `RB=F`, and `MTF=F`). It supports the Brent price summary and chart and provides daily OHLCV history for the Strategy Desk indicators. Third-party availability and update timing are outside Dark Wake's control.

### 8.2 TankerMap

The backend parses TankerMap's publicly rendered pages for:

- Daily Hormuz transit records.
- Daily Bab el-Mandeb transit records.
- Recent Bab el-Mandeb vessel-position rows and derived in-zone counts.
- Public TankerMap news headlines.

The integration uses those rendered public pages, not TankerMap's private `/api/` routes. The data is subject to TankerMap's publication coverage and update schedule.

### 8.3 Straits.live

The backend requests Straits.live's aggregate vessel endpoint for the Hormuz region. It validates the counts and source timestamp before storing a snapshot. A snapshot is considered fresh for API presentation for up to ten minutes.

### 8.4 IMF PortWatch

PortWatch supplies historical/daily chokepoint vessel records, including tanker and container counts and tanker capacity values where available. The backend calculates a rolling baseline and deviation for the local telemetry record. The API can convert capacity in metric tons to an approximate barrel equivalent using 7.33 barrels per metric ton. This is an estimate, not measured flow.

### 8.5 Selecting the daily transit source

For each monitored chokepoint, the API compares the latest available TankerMap date with the latest available PortWatch date. If TankerMap is at least as recent, its series is selected; otherwise PortWatch's series is used. The API returns source labels and dates to let the interface identify where the displayed record came from.

The TankerMap daily series and PortWatch oil-flow estimate are not merged into a synthetic common metric. TankerMap daily values can include LNG, crude, and product categories; the API returns a TankerMap breakdown where available.

### 8.6 RSS publishers

RSS ingestion reads OilPrice, CNBC Energy, and EIA Today in Energy feeds. EIA is assigned a longer 30-second fetch timeout because its feed can respond more slowly; other feeds use the default 10-second timeout. Feed failures are logged per source and should not prevent the worker from attempting the other feeds.

## 9. Storage, server responsibilities, and privacy boundaries

### 9.1 End-user computer

The standard desktop client does not require a database on the user's computer. The displayed research data is fetched from the hosted service into frontend memory. Users do not need a Supabase account or local environment file.

### 9.2 Backend SQLite

The backend uses SQLAlchemy with SQLite for PortWatch records, TankerMap daily transit records, and live chokepoint snapshots. The database URL is configurable through `DATABASE_URL`. The Docker configuration defaults it to:

```text
sqlite:////data/oil_intelligence.db
```

Persistence of that path depends on the host mounting a persistent disk. On an ephemeral container filesystem, SQLite contents can be lost on restart or redeploy; startup ingestion repopulates sources where they are reachable but does not guarantee the restoration of all previous history.

### 9.3 Supabase

Supabase is configured on the server through environment variables. Current backend code uses it for RSS storage/feed responses, saved analyses in the existing `war_room_debates` table, forecast predictions and agent-accuracy scores, and cloud telemetry synchronization when configured. Run `sql/strategy_desk_memory.sql` in the Supabase SQL editor to create the two new memory tables before enabling forecast-memory functionality. Credentials are server-side implementation details, not user setup.

### 9.4 Secrets

The Meta Model API key and Supabase service key must only be supplied to the backend host's secret/environment settings. They must never be placed in the desktop executable, a public repository, a public issue, or this local app description.

The current client-server API is publicly reachable at its configured URL and the backend has permissive CORS configuration. CORS is not authentication. The deployment operator should review access controls, rate limits, and usage limits before treating public write/compute endpoints as safe for unrestricted use.

## 10. Backend API overview

The FastAPI service exposes OpenAPI documentation at `/docs` and includes these principal paths:

| Route | Method | Purpose |
| --- | --- | --- |
| `/` | GET | Basic API status and endpoint list |
| `/health` | GET | Simple health response (`{"status":"ok"}`) |
| `/api/chokepoints` | GET | Daily chokepoint records, source dates, and live-snapshot metadata; accepts optional `chokepoint_name` filter |
| `/api/market/prices` | GET | Brent price and recent chart history |
| `/api/news/feed` | GET | Saved RSS headlines combined with TankerMap public headlines |
| `/api/strategy-desk/debates` | GET | Checks for due analysis and returns recent saved analysis history |
| `/api/strategy-desk/run` | POST | Checks/runs an analysis and returns its n8n-ready result |
| `/api/run-analysis` | POST | Analysis trigger endpoint |
| `/api/ingest-trigger` | POST | Manually triggers IMF PortWatch ingestion |

The desktop application uses the read endpoints; not every endpoint is exposed as a visible user action. Strategy Desk endpoints can invoke paid/quota-limited AI work when the latest analysis is not recent. Operators should protect or rate-limit compute/ingestion endpoints as appropriate.

## 11. Technology stack

### Desktop/frontend

- React for the user interface.
- Vite for frontend development and production bundling.
- Tauri 2 for the Windows desktop shell and NSIS installer.
- `VITE_API_BASE_URL` to set the backend API origin at frontend build time.

The production URL is configured in `dark-wake/.env.production`. Changing the backend hostname requires updating that file and rebuilding the installer.

### Backend

- Python and FastAPI for HTTP endpoints.
- Uvicorn as the ASGI server.
- APScheduler for recurring ingestion and debate jobs.
- SQLAlchemy and SQLite for server-side telemetry storage.
- Supabase for selected cloud persistence.
- `yfinance`, Requests, `feedparser`, and page parsers for source retrieval.
- LangGraph for the eight-stage Strategy Desk workflow.
- Requests for Meta Model API Responses API calls.

The repository Dockerfile runs the API on `0.0.0.0:7860`, a port supported by the earlier Docker Space configuration. Render also successfully ran the Docker image at that port. The public HTTPS URL is provided by the deployment host; it is not served by the local executable.

## 12. Running the project locally (for contributors)

Ordinary desktop users should use a published installer. Developers can run the backend and UI separately.

### Backend

1. Install Python 3.11 or newer.
2. From the repository root, create and activate a virtual environment.
3. Install `requirements.txt`.
4. Copy `.env.example` to `.env`.
5. Configure the server credentials required for the features being tested, such as `META_MODEL_API_KEY`, `META_MODEL_NAME`, `SUPABASE_URL`, and `SUPABASE_KEY`. Execute `sql/strategy_desk_memory.sql` in Supabase before testing prediction memory.
6. Run `uvicorn main:app --reload` from the repository root.

The backend listens locally at `http://localhost:8000` by default. Its OpenAPI docs are at `http://localhost:8000/docs`.

### Desktop development

1. Install Node.js and the platform prerequisites for Tauri.
2. From `dark-wake`, install the JavaScript dependencies.
3. Run `npm run tauri dev` to start the Tauri development app, or `npm run dev` for the Vite browser UI.

When no build-time API base URL is set, the frontend defaults to `http://localhost:8000`.

### Production Windows installer

From the repository root, the tracked production setting and build command are:

```powershell
npm --prefix dark-wake run tauri -- build --bundles nsis
```

The installer is output under `dark-wake/src-tauri/target/release/bundle/nsis/`. Review `dark-wake/.env.production` before publishing to confirm that it points to the intended backend. A new installer must be built and attached to a GitHub Release to make it a public downloadable desktop version.

## 13. Freshness, outages, and troubleshooting

- **API health:** open `<backend-url>/health`; a normal response is HTTP 200 with `{"status":"ok"}`. This checks that the API responds, not that every data provider is healthy.
- **API docs:** open `<backend-url>/docs` to inspect the currently running API.
- **No current traffic record:** check source ingestion logs, returned `data_as_of`, source labels, and the backend SQLite persistence configuration.
- **Old data:** the client polls frequently, but polling only retrieves what the backend currently has. Confirm that the hosting service is awake and scheduled ingestion has run.
- **Slow first load:** a host that sleeps while idle may need time to start when first requested.
- **Missing headlines:** check RSS fetch warnings, Supabase configuration/schema, and the public TankerMap news fetch.
- **Strategy Desk error:** confirm the server-side Meta Model API key/model and quota, Supabase URL/key and required memory tables, and whether the current analysis response is available. Model calls can take time or fail transiently.
- **No offline updates:** the desktop cannot fetch data if it has no network connection or the public backend is unavailable.
- **Windows SmartScreen:** the current installer is unsigned. Windows may warn that the publisher is unknown. Code signing can identify the publisher and help build reputation, but does not guarantee that SmartScreen warnings disappear immediately.

## 14. Research methodology and responsible use

Dark Wake is useful as a research workspace because it places price context, maritime-transit indicators, source-linked news, technical measures, and opposing analyst arguments together. A user can:

1. Observe the current displayed Brent price and recent movement.
2. Compare daily transit activity at Hormuz and Bab el-Mandeb.
3. Review the source and as-of date instead of treating all counts as the same live measure.
4. Open publisher links to assess headline context.
5. Compare the technical, bullish, and bearish reasoning.
6. Inspect the risk manager's final rationale, levels, and caveats.

The debate format is valuable because markets have competing causal explanations: a shipping disruption can create upside supply risk, while demand weakness or additional production can create downside pressure. Requiring a bearish rebuttal after the bullish thesis makes counterarguments visible; having a risk-manager stage then forces explicit synthesis rather than presenting both cases without a decision framework.

These are process advantages, not proof that the resulting conclusion is correct. The AI can misunderstand evidence, miss relevant events, express false precision, or inherit stale/incomplete source data. Verify material facts with primary sources, use independent risk controls, and never treat a displayed signal as personalized financial advice.

## 15. Project limitations and roadmap considerations

The current implementation has deliberate boundaries users should understand:

- It is a desktop research client backed by a hosted API, not a self-contained offline desktop database.
- Chokepoint cards show daily counts, not vessel-by-vessel locations.
- Live snapshot metadata is available from the API, but the interface does not render a live ship map.
- Upstream data cadence and accuracy vary by provider.
- Market price fallback values can be shown if Yahoo Finance returns no usable history; confirm a price before making decisions.
- Headline sentiment is a simple heuristic.
- The configured Meta model is used for the distinct sequential analyst roles; model availability and fallback behavior depend on provider support.
- Agent output is constrained and validated, but validation cannot guarantee analytical correctness.
- A sleeping/restarted backend may pause scheduled refreshes or lose non-persisted SQLite data depending on its storage configuration.
- AI access, hosting, and data-source terms, quotas, and prices can change over time.
- Public API endpoints should be reviewed for authentication, abuse prevention, and spending controls as usage grows.

---

## 16. Phase 3 — SAM 3.1 Computer Vision, Spatial Intelligence Tab & n8n Media Contract

Implemented on branch `meta-hackathon-upgrade` (do not merge to `main` until project fully finished).

### 16.1 SAM 3.1 Vision Module (`src/vision.py`)
- Mock SAM 3.1 endpoint (`SAM_3_1_ENABLED=False`). Live endpoint raises `NotImplementedError`; no live API credits burned during tests or runtime.
- Processes satellite map tiles for Strait of Hormuz, Bab el-Mandeb, and Malacca Strait.
- Returns Spatial Congestion Index (0–100), segment bounding boxes, vessel count, latency risk, and mask reference.
- Zero-fail fallback: placeholder PNG snapshots in `assets/satellite_chokepoints/` (`hormuz.png`, `bab_el_mandeb.png`, `malacca.png`). Replace with real satellite imagery when available.
- Unit tests (`tests/test_vision.py`, 5 cases) pass cleanly.

### 16.2 Strategy Desk Integration (`src/agents.py`)
- `vision.py` imported; `_inject_spatial_telemetry()` injects congestion index and bottleneck telemetry into Turn 1 (Technical Analyst) and Turns 2/3 (Supply/Demand Thesis) before text fallbacks.
- `META_MODEL_API_ENABLED=False` preserved (hard-coded disable — do not flip until project fully finished; see §16.6).

### 16.3 Frontend — Dedicated "Spatial Intelligence" Tab (`App.jsx`)
- New top-level nav tab: **Spatial Intelligence** (SAM 3.1 Vision).
- Interactive chokepoint selector (Hormuz / Bab el-Mandeb / Malacca).
- SAM 3.1 Viewer Frame with satellite tile + color-coded segmentation mask overlay (red >70, amber >40, green ≤40).
- Spatial Telemetry Panel: Congestion Index, vessel count, latency risk, SAM token metadata.

### 16.4 n8n Media Contract (`POST /api/strategy-desk/run` & `/api/strategy-desk/debates`)
Response payload now explicitly includes all fields required by the n8n media pipeline:
- `broadcast_script`: 60-second TTS-ready voiceover.
- `thumbnail_prompt`: Muse Image generation prompt (high-contrast charts, chokepoint maps, bullish/bearish motifs).
- `youtube_metadata`: `{ title, description, tags[] }`.
- `spatial_congestion`: `{ chokepoint, index, vessel_count, mask_ref }`.

### 16.5 RSS Headline Cap (Supabase)
- `RSS_HEADLINE_LIMIT=100`; `_prune_rss_headlines()` enforces first-in-last-out (delete oldest when 100 reached).
- Endpoint and tests updated.

### 16.6 Hard-Coded Meta API Disable (REMEMBER — change when finished)
- `META_MODEL_API_ENABLED=False` in `src/agents.py`, scheduler, and README.md.
- **DO NOT USE LIVE META API** until project fully finished. Flip to `True` only after all Phase 3 work is verified and committed.
- All SAM 3.1 vision calls are mocked (`SAM_3_1_ENABLED=False`).

### 16.7 Windows Tauri Build Prerequisite
- Tauri desktop build requires MSVC `link.exe` (Visual Studio 2017+ or Build Tools for Visual Studio with C++ option). VS Code alone is insufficient. See §15 / README.md.

### 16.8 Git Workflow (executed after verification)
- Branch: `meta-hackathon-upgrade` (work exclusively here; do not merge to `main`).
- After full test suite passes: `git add .`; `git commit -m "feat: implement SAM 3.1 computer vision (src/vision.py), dedicated Spatial Intelligence UI tab, and n8n media contract"`; `git push origin meta-hackathon-upgrade`.

---

**In short:** users install a small desktop app and view the data; the hosted backend performs collection, scheduling, persistence, AI orchestration, and SAM 3.1 vision processing (mocked until finished). The Meta API and SAM 3.1 live endpoints remain disabled by hard-coded guard until the project is fully finished. Replace placeholder satellite PNGs with real tiles when available; flip `META_MODEL_API_ENABLED=True` only at final completion.
