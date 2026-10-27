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

Dark Wake combines energy-market prices, commercial news, maritime-route telemetry, and a multi-agent Strategy Desk. The desktop client is built with Tauri and React; the API is a FastAPI service.

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
   META_MODEL_API_KEY=your_meta_model_api_key
   META_MODEL_NAME=meta-models/muse-spark-open-1026
   META_MODEL_API_BASE_URL=https://api.meta.ai/v1
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_KEY=your_supabase_service_role_key
   ```

   The Strategy Desk uses the Meta Model API. Supabase credentials are used for saved analyses, RSS news, and forecast-accuracy memory. Before enabling memory, execute [`sql/strategy_desk_memory.sql`](./sql/strategy_desk_memory.sql) in the Supabase SQL editor. Existing analysis history remains in the `war_room_debates` table. Keep `.env` private; it is ignored by Git.

5. Start the API from the repository root:

   ```powershell
   uvicorn main:app --reload
   ```

   The API is available at `http://localhost:8000`; interactive API docs are at `/docs`.

### Desktop app

Install Node.js and Rust. On Windows, also install Visual Studio 2022 or
Visual Studio Build Tools 2022 with the **Desktop development with C++**
workload, including the MSVC C++ build tools and a Windows SDK. Rust's
`*-pc-windows-msvc` target needs the MSVC linker (`link.exe`); VS Code alone
does not provide it.

After installation, open a new terminal (or use **Developer PowerShell for
Visual Studio 2022**) so the compiler environment is available. If Cargo still
reports that `link.exe` is missing, verify it in that terminal with:

```powershell
where.exe link
```

Then, from `dark-wake`:

```powershell
npm install
npm run tauri dev
```

For browser-only frontend development, use `npm run dev`. By default, the client connects to the local API at `http://localhost:8000`.

#### Meta Model API disabled during development

Meta Model API requests and Strategy Desk debate runs are hard-disabled in the
backend while the project is under development. Starting the backend still
allows other data ingestion and frontend testing, but it will not call the Meta
Model API or automatically schedule a Strategy Desk run. The manual run
endpoints also return an error while disabled; loading saved debate history is
still available.

When the project is complete and Meta Model API calls are intended, change
`META_MODEL_API_ENABLED` from `False` to `True` in [`src/agents.py`](./src/agents.py).
This enables Meta Model requests, manual debate runs, and the scheduled daily
run. Keep it `False` during development and testing.

## Build and sign the Windows installer with SignPath

Dark Wake is applying to use the SignPath Foundation for code signing its
open-source Windows releases. Once the project is approved and signing is
enabled, signed releases will identify SignPath Foundation as the certificate
provider. Until then, published installers may be unsigned.

The `.github/workflows/windows-signpath.yml` workflow builds the NSIS installer
on a GitHub-hosted Windows runner, uploads the unsigned installer to GitHub
Actions, submits that artifact to SignPath, verifies the returned Authenticode
signature, and uploads the signed installer. When started by pushing a `v*`
tag, it also publishes the signed installer as a GitHub Release asset. A
manual `workflow_dispatch` run builds and signs the selected branch or tag and
retains the signed installer as a downloadable workflow artifact.

### SignPath setup

This workflow does not create a SignPath account, project, certificate, or
signing policy. Apply to the SignPath Foundation and complete its project
configuration first. The Foundation must approve the project and signing
requests; signing and SmartScreen reputation are not guaranteed.

The repository is licensed under the MIT License; see `LICENSE`. The
Foundation must still approve the project before this workflow can submit
signing requests.

After SignPath provides the organization, project, signing-policy, and
artifact-configuration values, configure the repository at **Settings →
Secrets and variables → Actions**:

- Add the SignPath API token as the `SIGNPATH_API_TOKEN` Actions secret.
- Add `SIGNPATH_ORGANIZATION_ID`, `SIGNPATH_PROJECT_SLUG`, and
  `SIGNPATH_SIGNING_POLICY_SLUG` as Actions variables.
- Add `SIGNPATH_ARTIFACT_CONFIGURATION_SLUG` as an Actions variable if the
  SignPath project requires a non-default artifact configuration.
- Configure the artifact configuration to accept the single unsigned
  `dark-wake_<version>_x64-setup.exe` file uploaded by the workflow, and set
  the signing policy to the certificate and approval process assigned to the
  project.

Do not commit the API token. The workflow requires `actions: read` to let
SignPath verify and retrieve the GitHub Actions artifact, and `contents: write`
to publish a tagged release.

### Run the signing workflow

After merging the workflow and completing SignPath setup, run **Build and sign
Windows installer** from the repository's Actions tab using **Run workflow**
and select `main`. The signed installer will be available as a downloadable
workflow artifact. The existing `v0.2.1` tag predates this workflow, so upload
that artifact manually to the existing GitHub Release if you are signing that
version.

For a future release, first update all app version metadata and merge it to
`main`, then push a matching version tag. For example, after updating the app
version to `0.2.2`:

```powershell
git tag v0.2.2
git push origin v0.2.2
```

The tag-triggered run builds and signs that version, then publishes the signed
installer as a GitHub Release asset. The tag must match the app version.

The installer uses Tauri's offline WebView2 installer mode. This embeds the
WebView2 runtime and makes the installer roughly 127 MB larger, but allows
installation without downloading the runtime separately. The workflow does
not replace Tauri's NSIS installer scripts or change NSIS silent-install
behavior (the setup executable's `/S` switch remains available).

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

- `META_MODEL_API_KEY` as a secret.
- `META_MODEL_NAME` as a variable.
- `SUPABASE_KEY` as a secret.
- `SUPABASE_URL` as a variable.

Do not upload `.env` or put secrets in the Dockerfile. The Space gets these values as runtime environment variables. The API uses SQLite at `/data/oil_intelligence.db` in the container. Space disk contents are not durable across restarts unless persistent storage is configured; use Supabase for Strategy Desk history, forecast memory, and RSS data.

When the Space is running, check `https://<your-space-url>/health` and `https://<your-space-url>/docs`. Copy the HTTPS base URL shown for your Space; do not include `/api` at the end.

> **Availability note:** Hugging Face's current documentation says Docker Spaces require an eligible paid plan to create, even though CPU Basic hardware has no hourly usage charge. Free hardware may sleep after inactivity. While asleep, scheduled ingestion and Strategy Desk jobs do not run, and the first request after sleep may be slow. Check current plan and storage terms in your account; persistent storage and uninterrupted scheduling may require a paid configuration.

## Build the Windows desktop app for the hosted API

The production frontend is configured to use the Render backend URL in `dark-wake/.env.production`. From the repository root, build the Windows installer:

```powershell
npm --prefix dark-wake run tauri -- build --bundles nsis
```

Tauri writes the Windows installer under `dark-wake/src-tauri/target/release/bundle/nsis/`. Update `.env.production` and rebuild whenever the backend URL changes. Never put Meta Model API or Supabase secret keys in the desktop build.

The installer bundles the offline WebView2 runtime and is therefore much larger
than the small bootstrapper-based installer. The NSIS `/S` silent-install
switch remains supported.

## Data sources

- Straits.live provides recent Hormuz vessel counts.
- TankerMap public pages provide daily chokepoint transits, recent Bab el-Mandeb observations, and news headlines.
- IMF PortWatch provides historical vessel and oil-flow estimates.
- The Strategy Desk uses the Meta Model API and stores its analyses in Supabase.

The Strategy Desk refreshes once daily at 08:00 Europe/London time. London daylight-saving changes are handled by the scheduler.
