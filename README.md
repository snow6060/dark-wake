---
title: Dark Wake API
emoji: "🛢️"
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Dark Wake

Dark Wake combines oil-market prices, news, chokepoint vessel telemetry, and a multi-agent market analysis War Room. The desktop client is built with Tauri and React; the API is a FastAPI service.

## Run locally

### Backend

1. Install Python 3.11 or newer.
2. From the repository root, create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install the backend dependencies and make your local environment file:

   ```powershell
   pip install -r requirements.txt
   Copy-Item .env.example .env
   ```

4. Open the root `.env` file and set the API keys:

   ```dotenv
   GOOGLE_API_KEY=your_google_api_key
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_KEY=your_supabase_service_role_key
   ```

   `GOOGLE_API_KEY` is used by the War Room. Supabase credentials are needed for saved War Room analyses and RSS news. Keep `.env` private; it is ignored by Git.

5. Start the API from the repository root:

   ```powershell
   uvicorn main:app --reload
   ```

   The API is available at `http://localhost:8000`; interactive API docs are at `/docs`.

### Desktop app

Install Node.js, then from `dark-wake`:

```powershell
npm install
npm run tauri dev
```

For browser-only frontend development, use `npm run dev`. By default, the client connects to the local API at `http://localhost:8000`.

## Deploy the backend to Hugging Face Spaces

The repository includes a Dockerfile and Hugging Face Docker Space metadata. Create a **Docker Space**. To deploy this repository while keeping its Hugging Face Git history:

1. Clone the new Space repository in a separate folder:

   ```powershell
   git clone https://huggingface.co/spaces/<your-username>/<your-space-name> ..\dark-wake-space
   ```

2. Copy `README.md`, `Dockerfile`, `.dockerignore`, `main.py`, `requirements.txt`, and `src/` from this repository into that cloned Space folder. Do not copy `.env`, virtual environments, or local database files.
3. From the cloned folder, commit and push the copied files:

   ```powershell
   git add README.md Dockerfile .dockerignore main.py requirements.txt src
   git commit -m "Deploy Dark Wake API"
   git push
   ```

   Authenticate with a Hugging Face token that has write access when Git prompts. The container listens on port `7860`; Hugging Face provides the public HTTPS URL for the running Space.

In the Space's **Settings → Variables and secrets**, add:

- `GOOGLE_API_KEY` as a secret.
- `SUPABASE_KEY` as a secret.
- `SUPABASE_URL` as a variable.

Do not upload `.env` or put secrets in the Dockerfile. The Space gets these values as runtime environment variables. The API uses SQLite at `/data/oil_intelligence.db` in the container. Space disk contents are not durable across restarts unless persistent storage is configured; use Supabase for War Room history and RSS data.

When the Space is running, check `https://<your-space-url>/health` and `https://<your-space-url>/docs`. Copy the HTTPS base URL shown for your Space; do not include `/api` at the end.

> **Availability note:** Hugging Face's current documentation says Docker Spaces require an eligible paid plan to create, even though CPU Basic hardware has no hourly usage charge. Free hardware may sleep after inactivity. While asleep, scheduled ingestion and War Room jobs do not run, and the first request after sleep may be slow. Check current plan and storage terms in your account; persistent storage and uninterrupted scheduling may require a paid configuration.

## Build the Windows desktop app for the hosted API

The production frontend is configured to use the Render backend URL in `dark-wake/.env.production`. From the repository root, build the Windows installer:

```powershell
npm --prefix dark-wake run tauri -- build --bundles nsis
```

Tauri writes the Windows installer under `dark-wake/src-tauri/target/release/bundle/nsis/`. Update `.env.production` and rebuild whenever the backend URL changes. Never put Google AI or Supabase secret keys in the desktop build.

## Data sources

- Straits.live provides recent Hormuz vessel counts.
- TankerMap public pages provide daily chokepoint transits, recent Bab el-Mandeb observations, and news headlines.
- IMF PortWatch provides historical vessel and oil-flow estimates.
- The War Room uses Gemini through the Google AI API and stores its analyses in Supabase.

The War Room refreshes every 12 hours at 09:00 and 21:00 Europe/London time. London daylight-saving changes are handled by the scheduler.
