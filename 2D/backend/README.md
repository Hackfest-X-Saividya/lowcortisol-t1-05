# Nishaan backend

AI crime scene and suspect sketch generator for police: a witness's spoken account (Hindi,
Kannada or English) becomes a suspect sketch that is refined one feature at a time, plus a
3D crime-scene layout. **Investigative aid only. Not an identification.**

This is the *light build*: it runs on an ordinary laptop with no GPU, no Docker, no Redis
and no Postgres. Heavy AI work goes to free cloud tiers (Google Gemini, Groq, Cloudflare
Workers AI, optionally Pollinations); everything else is plain Python, OpenCV and SQLite.
With `AI_MODE=mock` the whole flow runs fully offline.

## Setup

Requirements: Python 3.11 or newer (tested on 3.13), about 2 GB of disk for the venv.

### Windows (PowerShell)

```powershell
cd backend
py -3 -m venv .venv            # or: uv venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python scripts\download_assets.py
python scripts\make_placeholder_overlays.py
alembic upgrade head
python -m app.seed.seed        # prints the demo users' passwords and the witness token ONCE
uvicorn app.main:app --reload
```

### macOS / Linux

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python scripts/download_assets.py
python scripts/make_placeholder_overlays.py
alembic upgrade head
python -m app.seed.seed
uvicorn app.main:app --reload
```

Then open `http://localhost:8000/docs`. `GET /api/v1/ready` shows the database state, which
providers are configured and the `data_mode`. The frontend guide is in `API.md`.

If the model or font downloads fail, the app still runs: sketch generation falls back to
template landmarks and the PDF to a built-in font.

## The `.env` file

`backend/.env` holds six keys and is never committed, printed or logged. Leave a key empty
and the related provider falls back to its deterministic mock. All other settings have
defaults; `.env.example` lists every one with a comment.

| Key | Where to get it |
|---|---|
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/) -> *Get API key* |
| `GROQ_API_KEY` | [Groq console](https://console.groq.com/keys) -> *API Keys* |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare dashboard -> *Workers & Pages* -> Account ID (right-hand column) |
| `CLOUDFLARE_API_TOKEN` | Cloudflare dashboard -> *My Profile* -> *API Tokens* -> *Create Token* -> **Workers AI** template |
| `JWT_SECRET` | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `FILE_MASTER_KEY_B64` | `python -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"` |

`JWT_SECRET` signs staff access tokens. `FILE_MASTER_KEY_B64` is the master key for the
AES-256-GCM file store; every stored file (audio, images, exports) is encrypted with a
per-file key derived from it. Losing it makes existing files unreadable. In development the
app starts with ephemeral values if either is missing (and warns); in `APP_ENV=production`
it refuses to start.

## Mock mode vs cloud mode

| | `AI_MODE=mock` | `AI_MODE=cloud` (default) |
|---|---|---|
| Speech to text | fixed transcripts from `tests/fixtures` | Groq Whisper (`whisper-large-v3`) |
| LLM (extraction, questions, translation, edit routing, scene) | keyword rules | Gemini, backup Groq, then mock |
| Face image | synthetic OpenCV face at the canonical geometry | Cloudflare SDXL-lightning, fallback Pollinations, then mock |
| Inpainting (hair/skin/texture) | deterministic tint | Cloudflare SD 1.5 inpainting |
| Landmarks | canonical template | MediaPipe Face Landmarker (CPU) |
| Network | none | required |

**Cloud mode sends audio, transcripts and prompts to Google, Groq and Cloudflare. Use demo
data only.** The app logs a warning at startup and `/ready` reports
`"data_mode": "cloud_demo"`. `CLOUD_MODE_ACK=true` records that this is acknowledged;
setting it to `false` disables every cloud provider. The provider layer is behind
interfaces (`app/providers/base.py`) so a police deployment can swap in self-hosted models
without touching the services.

Model names change. The defaults (`GEMINI_MODEL`, `GROQ_LLM_MODEL`, `GROQ_ASR_MODEL`,
`CF_IMAGE_MODEL`, `CF_INPAINT_MODEL`) were verified against each provider's model list on
2026-10-28; check them in AI Studio, the Groq console and the Cloudflare Workers AI
catalogue when something returns 404. `python scripts/smoke_test_providers.py` makes one
tiny call per configured provider and prints `ok` or `failed: <reason>` without ever
printing a key.

### Saving free quota

`PROVIDER_CACHE=true` (default) stores every cloud response, encrypted, keyed by the
SHA-256 of (provider, model, normalized request). Re-running the same demo statement,
question or image prompt costs nothing. Transcripts are only reused for byte-identical
audio. The cache lives in the `provider_cache` table plus the file store.

## Running the tests

```bash
pytest                      # 158 tests, all offline (network is blocked in conftest.py)
pytest --cov                # coverage for app/core and app/services (88%)
ruff check . && ruff format --check . && mypy app
```

Tests force `AI_MODE=mock`, `JOBS_INLINE=true` and a fresh SQLite file per test. Coverage
uses the `sysmon` core (configured in `pyproject.toml`); the default C tracer misses lines
that run under SQLAlchemy's greenlet bridge.

## Useful scripts

| Script | Purpose |
|---|---|
| `scripts/download_assets.py` | MediaPipe `face_landmarker.task` and the Noto fonts (prints the source URL of each) |
| `scripts/make_placeholder_overlays.py` | placeholder accessory PNGs and `assets/overlays/anchors.json` (replace with better art) |
| `scripts/smoke_test_providers.py` | one tiny request per configured provider |
| `scripts/verify_audit_chain.py` | recompute the audit hash chain, report the first broken row |
| `python -m app.seed.seed` | demo users, case, witness, session |

## Project layout

```
app/
  main.py, config.py, container.py       app factory, settings, lifetime objects
  core/        security (JWT, argon2id, witness tokens), rbac, crypto (AES-GCM), audit (hash chain),
               events (WebSocket bus), jobs (in-process runner), ratelimit, errors, logging
  api/         FastAPI routes (no business logic) and the WebSocket
  services/    the actual logic: cases, statements, interview engine, sketch pipeline, scene, exports
  providers/   LLM / ASR / image / inpaint interfaces, mocks, Gemini, Groq, Cloudflare, Pollinations, cache
  db/          SQLAlchemy models and repositories (SQLite now, Postgres by changing DATABASE_URL)
assets/        MediaPipe model, fonts, overlays, scene templates, canonical face template
alembic/       migrations (the initial one also creates the append-only audit triggers)
tests/         unit + integration (httpx AsyncClient, jobs inline)
```

Design notes and deviations from the original brief are in `DECISIONS.md`; the build plan in
`PLAN.md`.

## Licences

| Component | Licence | Notes |
|---|---|---|
| FastAPI, Starlette, Uvicorn, Pydantic, pydantic-settings, httpx, respx | MIT / BSD-3 | |
| SQLAlchemy, aiosqlite, Alembic, greenlet | MIT | |
| PyJWT, argon2-cffi, slowapi, jsonpatch | MIT / BSD | |
| cryptography | Apache-2.0 / BSD-3 (dual) | |
| NumPy, scikit-image, Pillow | BSD-3 / MIT-CMU (Pillow) | |
| OpenCV (`opencv-contrib-python`, pulled in by MediaPipe) | Apache-2.0 | the `contrib` wheel includes some non-free algorithms; this project only uses core functions (`warpAffine`, `remap`, `seamlessClone`, drawing) |
| MediaPipe + Face Landmarker model | Apache-2.0 | model card: Google MediaPipe |
| ReportLab (open-source) | BSD-3 | |
| google-genai SDK | Apache-2.0 | |
| Noto Sans, Noto Sans Devanagari, Noto Sans Kannada | SIL Open Font License 1.1 | |
| pytest, pytest-asyncio, pytest-cov, ruff, mypy | MIT | |
| Google Gemini API (free tier) | Google AI terms of service | verify before use for police data; free tier may use prompts for product improvement |
| Groq API (free tier) | Groq terms of service | verify before use |
| Cloudflare Workers AI (free tier) | Cloudflare terms of service | verify before use |
| Pollinations.ai | free public service, no key | verify before use; no SLA, images may carry a watermark on some endpoints |

Anything marked "verify before use" has terms that may change; check them before any
non-demo deployment.
