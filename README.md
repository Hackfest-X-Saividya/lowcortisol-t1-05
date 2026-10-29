# Nishaan

One app with two parts:

| Folder | What | Port |
|---|---|---|
| `2D/` | Witness interview, live composite sketch, crime scene wall, vault, timeline (React + FastAPI) | web 5173, API 8000 |
| `3D MODEL/` | 3D face builder: AI builds a realistic 3D head from a description (Flask service + Three.js page) | 5001 |

In the witness window, **Evidence index → 3D model** opens the 3D face builder directly on its
AI face builder. The 2D web app serves the `3D MODEL` page unchanged under `/nishaan3d/`
(`2D/frontend/nishaan3d.js`); the page talks to the 3D face service on port 5001.
`3D MODEL/` also still runs on its own as the desktop app (`npm start` in that folder).

## Setup (once)

Keys go in `.env` in this folder (gitignored, never commit it): `GROQ_API_KEY`,
`GEMINI_API_KEY`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, `JWT_SECRET`,
`FILE_MASTER_KEY_B64`.

```powershell
# 2D backend (Python 3.11+; uv or python -m venv)
cd 2D\backend
uv venv .venv; uv pip install --python .venv\Scripts\python.exe -e ".[dev]"
.\.venv\Scripts\python.exe -m app.seed.seed     # demo users + witness code, printed once
cd ..\frontend; npm install

# 3D face builder (Anaconda Python; Blender 5.x found automatically)
cd "..\..\3D MODEL"
pip install -r backend\requirements.txt          # never install google-generativeai
npm install
```

## Run

```powershell
powershell -ExecutionPolicy Bypass -File start-nishaan.ps1
```

Starts the 2D backend, the 3D face service and the web app in their own windows (a part whose
port is already taken is skipped with a warning), then open http://localhost:5173.
