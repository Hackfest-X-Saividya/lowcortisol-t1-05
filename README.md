# NISHAAN

**Every witness holds a face.**

NISHAAN is a witness-led suspect sketch and crime scene tool. A witness describes what they saw, in English, Hindi or Kannada, and the app builds a refinable composite sketch, a realistic 3D head and a crime scene wall. Officers keep the case, the evidence vault and the timeline in one place.

It is one app made of two parts that run side by side.

| Part | Folder | What it does | Stack | Port |
|------|--------|--------------|-------|------|
| 2D app | `2D/` | Witness interview, live composite sketch, crime scene wall, evidence vault, timeline | React + FastAPI | Web `5173`, API `8000` |
| 3D face builder | `3D MODEL/` | AI builds a realistic 3D head from a description, built on Blender | Flask service + Three.js page + Blender | `5001` |

> The sketch is an investigative lead, not proof of identity. Every export carries that disclaimer.

---

## Contents

1. [How the parts connect](#1-how-the-parts-connect)
2. [Quick start](#2-quick-start)
3. [Requirements](#3-requirements)
4. [Setup (once)](#4-setup-once)
5. [Run](#5-run)
6. [The 3D face builder and Blender](#6-the-3d-face-builder-and-blender)
7. [Multilingual support](#7-multilingual-support)
8. [The 2D app](#8-the-2d-app)
9. [Roles: staff and witness](#9-roles-staff-and-witness)
10. [Security and audit](#10-security-and-audit)
11. [Offline mock mode](#11-offline-mock-mode)
12. [Ports at a glance](#12-ports-at-a-glance)
13. [Project layout](#13-project-layout)
14. [Troubleshooting](#14-troubleshooting)

---

## 1. How the parts connect

1. In the witness window, open **Evidence Index → 3D Model**. This opens the 3D face builder directly on its AI Face Builder.
2. The 2D web app serves the `3D MODEL/` page unchanged under `/nishaan3d/` (see `2D/frontend/nishaan3d.js`).
3. That page talks to the 3D face service on port `5001`.
4. `3D MODEL/` also runs on its own as a desktop app (`npm start` inside that folder).

---

## 2. Quick start

After the one-time setup in section 4, start everything with one command:

```powershell
powershell -ExecutionPolicy Bypass -File start-nishaan.ps1
```

Then open **http://localhost:5173**.

---

## 3. Requirements

| Tool | Used for |
|------|----------|
| Python 3.11+ (with `uv` or `python -m venv`) | 2D backend |
| Anaconda Python | 3D face service |
| Node.js and npm | 2D frontend and 3D page |
| Blender 5.x | 3D face builder (found automatically, no setup needed) |

The commands in this README are for Windows PowerShell.

---

## 4. Setup (once)

### 4.1 Add your keys

Create a `.env` file in the project root folder. It is gitignored. **Never commit it.**

| Key | Purpose |
|-----|---------|
| `GROQ_API_KEY` | AI provider key |
| `GEMINI_API_KEY` | AI provider key |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account for hosted AI |
| `CLOUDFLARE_API_TOKEN` | Cloudflare access token |
| `JWT_SECRET` | Signs login tokens |
| `FILE_MASTER_KEY_B64` | Master key for file encryption (base64) |

<!-- CONFIRM: Check the Purpose column above, and say which provider handles speech-to-text, translation and the interview questions. -->

### 4.2 Set up the 2D backend

```powershell
cd 2D\backend
uv venv .venv
uv pip install --python .venv\Scripts\python.exe -e ".[dev]"
.\.venv\Scripts\python.exe -m app.seed.seed
```

The last command creates the demo users and a witness code. They are **printed once**, so copy them down when they appear.

### 4.3 Set up the 2D frontend

```powershell
cd ..\frontend
npm install
```

### 4.4 Set up the 3D face builder

```powershell
cd "..\..\3D MODEL"
pip install -r backend\requirements.txt
npm install
```

> **Warning:** never install `google-generativeai` in the 3D environment.

---

## 5. Run

### Everything at once

```powershell
powershell -ExecutionPolicy Bypass -File start-nishaan.ps1
```

The script starts the 2D backend, the 3D face service and the web app, each in its own window. If a port is already taken, that part is skipped and a warning is shown.

Then open **http://localhost:5173**.

### 3D face builder on its own (desktop app)

```powershell
cd "3D MODEL"
npm start
```

---

## 6. The 3D face builder and Blender

The 3D face builder turns a text description into a realistic 3D head that you can rotate, edit and capture. The head is built with **Blender 5.x**, which the 3D face service finds automatically, so there is nothing to configure as long as Blender is installed.

<!-- CONFIRM: Describe exactly what Blender does in this pipeline. For example: builds the base head mesh, applies shape keys or morph targets from the AI's parameters, adds hair and accessories, and exports a file (glb, obj or other) that the Three.js page loads. Also state how the Flask service calls Blender (headless command line or a Python script) and where the exported files are saved. -->

### 6.1 How a face is built

1. The witness or officer types or speaks a description in the **AI Face Builder** panel, for example "Male, 30s, wide jaw, small eyes, dark skin, short hair".
2. The AI reads the description and turns it into face parameters.
3. The Flask service on port `5001` passes the parameters to Blender, which builds the 3D head.
4. The Three.js page loads the result into the viewport, where it can be viewed and edited.

### 6.2 Build with a witness

**Build with a witness** shows several faces from the description and narrows them down by which one looks closest. It costs one AI request. The rounds after the first are generated offline, which saves quota.

### 6.3 Tools in the 3D builder

| Area | What it offers |
|------|----------------|
| Tool tabs | Face, Hair, Look, Accs (accessories), AI, Snaps, Case |
| AI Face Builder | Model dropdown (default GPT-OSS 120B), example descriptions, quick chips (Broad male, Thin female, Wider nose, Reset), text, microphone and send buttons, reset and clear |
| View modes | Front, Side, 3/4, Top, plus a Studio lighting dropdown and a Wire (wireframe) view |
| Editing tools | Point Edit, Marks, Decal, Track, Face Capture |
| Action bar | Ref (reference), Undo, Redo, Screenshot, Reset All |
| Top bar | Save, Export, case name, online status |
| Readouts | Poly count, vertex count and FPS |

### 6.4 Why 3D

A 3D head can be viewed from the front, side and three-quarter angles, so a witness can confirm a profile that a flat sketch cannot show. The 2D app handles the interview and the pencil sketch, and the 3D builder adds the realistic head for staff.

---

## 7. Multilingual support

NISHAAN is built so a witness can describe a face in the language they think in.

### 7.1 Supported languages

| Language | Voice input | Text input | Interface |
|----------|-------------|------------|-----------|
| English | Yes | Yes | Yes |
| Hindi | Yes | Yes | Yes |
| Kannada | Yes | Yes | Yes |

English is the fallback language.

### 7.2 How it works

1. The witness speaks or types in their preferred language, chosen when the officer adds the witness to the case.
2. The transcript appears in the **original script** (Devanagari or Kannada), with an **English translation** beside it for staff.
3. The witness or officer can correct misheard words, and low-confidence words are underlined for confirmation.
4. The **original-language text is always the record**. The English translation is only a working copy used by the AI.
5. Questions are shown to the witness in their own language.

### 7.3 Spoken edits

A witness can change the sketch by speaking, for example "jabda thoda chauda karo" (make the jaw a little wider). The app turns this into a structured edit, using amount words:

| Amount word | Hindi / Kannada examples | Change |
|-------------|--------------------------|--------|
| A little | thoda / swalpa | 5% |
| More | aur / innu | 10% |
| A lot | bahut / tumba | 15% |
| No amount | (none) | Three previews (5%, 10%, 15%) to choose from |

### 7.4 Fonts and display

The interface uses Noto Sans Devanagari and Noto Sans Kannada so Hindi and Kannada text renders correctly. The typewriter display font used for English labels has no Hindi or Kannada glyphs, so those languages always use the Noto fonts.

<!-- CONFIRM: List which language options exist in the interface today (language switcher location, default language, and whether the 3D builder accepts Hindi and Kannada descriptions or only English). Also name the speech-to-text and translation services actually used. -->

---

## 8. The 2D app

The 2D app is the main workspace. Its Evidence Index has four sections: **Composite Sketch**, **Crime Scene Wall**, **Evidentiary Vault** and **Incident Timeline**.

### 8.1 Case files

Staff sign in, then open a case with a case number, crime type, location and the time it occurred. The station is taken from the officer's profile.

### 8.2 Witness interview

1. The witness describes everything in their own words before seeing any image.
2. The system extracts a feature sheet and marks what is missing.
3. It asks one question at a time, and every question allows "I don't remember".
4. Picture options show only the feature being asked about, never a full face.

### 8.3 Composite sketch

- The first face is built from a neutral, passport-style prompt that never contains crime words, and always states skin tone explicitly. It is generated with Cloudflare SDXL, with Pollinations as the fallback.
- MediaPipe checks that the image holds exactly one frontal face and aligns it to a canonical template, so every later version shares the same geometry.
- Edit with about 24 drag handles, eight sliders (jaw width, face length, eye size, eye spacing, nose length, nose width, lip fullness, brow height), or by speaking. Edits are a fast landmark warp, and locked features do not move at all.
- Accessories and marks (spectacles, cap, turban, helmet, face cloth, moustaches, beards, scar, mole, tilak, earrings) are placed from landmarks and re-applied after every later warp so they never distort.
- Hair, skin and texture changes can use optional cloud inpainting, composited so pixels outside the edit area are untouched.
- The witness only ever sees a pencil-style rendering. The realistic master image is staff-only and watermarked on export.

### 8.4 Versions and quality checks

Every edit creates a child version, and nothing is deleted, so the witness can branch from any older version. Each version records locked-landmark drift, similarity outside the edit area and a face-shape signature, with a warning when a threshold is exceeded. Witnesses rate versions closer or further, and any two versions can be compared.

### 8.5 Crime scene wall

The statement becomes a scene from a template (shop, room, street or junction), with objects, people, evidence markers and events, snapped to a 0.25 m grid with overlaps resolved. Edits are JSON patches or spoken commands, and locked objects cannot be moved. Each version reports the witness-to-suspect distance and whether the line of sight is clear or blocked, and by what.

### 8.6 Sign-off and exports

The witness signs off with a confidence level for each feature. Staff can export:

- a 2048 px sketch PNG,
- a watermarked photoreal PNG,
- a top-down scene PNG,
- a PDF report with case details, the sketch, a confidence table, the feature sheet, the transcript in the original script with English, the questions and answers, the version history, file hashes and the disclaimer.

### 8.7 Live updates

A WebSocket per session streams transcription, feature sheet, questions, job progress, versions, previews, scene changes and export events.

<!-- CONFIRM: Mark any feature in section 8 that is not finished yet (for example optional inpainting, compare view or the scene exports) so this README matches what runs today. -->

---

## 9. Roles: staff and witness

| | Staff (officer, supervisor) | Witness |
|---|---|---|
| Sign in | Username and password | No account. The officer opens the witness window for them, using a witness code |
| Sees | Everything: metrics, photoreal view, hashes, English translation, audit log | Pencil imagery only, large controls, at most three choices at a time |
| Can pause | Yes | Yes, a visible Pause is always on screen |

---

## 10. Security and audit

- Passwords are protected, and logins use signed tokens (`JWT_SECRET`).
- Case files are encrypted with the master key (`FILE_MASTER_KEY_B64`).
- Every read, write, login, export and every image shown to the witness is recorded as a hash-chained audit row. SQLite triggers make the log append-only.
- Supervisors can verify the chain and get the first broken row id.
- Real case data should stay on infrastructure the department controls. Use only non-sensitive demo data with cloud AI services.

---

## 11. Offline mock mode

With `AI_MODE=mock`, every AI provider is replaced by a deterministic local stand-in, so the whole flow runs with no network. In cloud mode, responses are cached to save free quota.

<!-- CONFIRM: State where to set AI_MODE (the .env file or the start script) and whether the 3D builder also honours it. -->

---

## 12. Ports at a glance

| Service | URL |
|---------|-----|
| Web app | http://localhost:5173 |
| 2D API | http://localhost:8000 |
| 3D face service | http://localhost:5001 |
| 3D page (served by the web app) | http://localhost:5173/nishaan3d/ |

---

## 13. Project layout

```
.
├── .env                    # your keys (gitignored, never commit)
├── start-nishaan.ps1       # starts all three services
├── 2D/
│   ├── backend/            # FastAPI API
│   └── frontend/           # React web app (includes nishaan3d.js)
└── 3D MODEL/
    └── backend/            # Flask face service
```

---

## 14. Troubleshooting

| Problem | What to check |
|---------|---------------|
| A part does not start | Its port (`5173`, `8000` or `5001`) may already be in use. The start script skips that part and prints a warning |
| The 3D head does not build | Check that Blender 5.x is installed, and that the 3D face service is running on port `5001` |
| The 3D page is blank inside the web app | Check that the 3D face service is running, because the page talks to it on port `5001` |
| Witness code or demo users are lost | They are printed only once by the seed command. Run it again to create new ones |
| Import errors in the 3D service | Make sure `google-generativeai` is not installed, and reinstall from `backend\requirements.txt` |
| AI features fail | Check the keys in `.env`, or switch to `AI_MODE=mock` to run offline |
