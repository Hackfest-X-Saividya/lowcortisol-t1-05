# Nishaan

**Build a suspect's face from a witness description.**

Nishaan is a desktop app for forensic facial reconstruction. A witness describes a
person — by typing or speaking — and an AI model turns the description into a
realistic 3D head. The investigator then refines every feature by hand, narrows
the likeness down with the witness, and saves, renders or exports the result.

The interface is styled as a detective's evidence wall: pinned manila notes, red
string and typewritten labels around a clean 3D viewport.

---

## Contents

- [Features](#features)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the app](#running-the-app)
- [Using Nishaan](#using-nishaan)
- [Testing](#testing)
- [Backend API](#backend-api)
- [Project structure](#project-structure)
- [3D assets](#3d-assets)
- [Troubleshooting](#troubleshooting)
- [Credits](#credits)
- [Responsible use](#responsible-use)
- [License](#license)

---

## Features

**Describe a face, get a face**
- Type a description in plain language, or speak it — voice is transcribed with
  Whisper and placed in the input box for review before sending.
- The AI reads age, sex, ancestry, build and individual features from the
  description and sets the whole face at once, including hair, beard, eye colour
  and accessories.
- Follow-up messages refine the current face ("make the nose narrower",
  "add glasses") instead of starting over.
- Reference photos can be attached to guide the AI.

**Realistic faces**
- The head is shaped by anatomical morph targets from MakeHuman, not by simple
  mesh pushes, so changes look like real human variation.
- **Person** controls reshape the entire face the way it changes in real people:
  age (18–90 years), sex, ancestry mix (African, East Asian, European), body
  weight and muscle.
- 50+ feature controls across skull, forehead, brows, eyes, nose, cheeks, mouth,
  jaw, chin and ears — plus under-eye bags, epicanthic fold, nose profile,
  chin cleft and double chin.
- Photographic skin that follows age, sex and ancestry automatically, with an
  optional skin-tone tint.
- Textured eyes with a real iris (any colour), a clear glossy cornea, strand-based
  eyebrows and eyelashes.

**Hair, facial hair and accessories**
- 14 hairstyles plus bald, 6 beards and a moustache, all textured, with colour,
  tint, length and volume controls.
- Glasses (4 styles with tintable lenses), two face masks, earrings, a bandana and
  an eyebrow ring.
- Skin marks, scars, moles, wrinkles, pigmentation and lip colour can be painted
  directly onto the face, and image decals placed on it.

**Working with a witness**
- **Build with a witness** shows several candidate faces generated from the
  description; the witness picks the closest and the app narrows down from there.
  Only the first round uses an AI request — later rounds are generated offline.
- Snapshots save any face state to return to later.
- A reference-photo overlay helps compare the model against an image.

**Output**
- High-quality renders through Blender.
- Export the head as OBJ, FBX or GLB.
- Save and reopen cases (`.rfc` files) with all case details and face settings.
- Screenshots and turntable video clips of the 3D view.

---

## How it works

```text
  Witness / investigator           Electron app (renderer)                 Python backend (Flask, port 5001)
  ──────────────────────           ───────────────────────                 ─────────────────────────────────
  types or speaks a      ───────▶  AI Face Builder panel     ── POST ──▶   /api/speech/transcribe → Groq Whisper
  description                      Three.js 3D viewport                    /api/ai/generate       → Groq or Gemini
                                   MakeHuman morph targets   ◀── JSON ──   (validated face parameters)
                                   textures, hair, accessories
                                   manual editing tabs        ── POST ──▶   /api/render, /api/export → Blender
                                                              ◀── file ──   (render PNG / OBJ / FBX / GLB)
```

1. The description (typed, or transcribed by Whisper) is sent to the backend.
2. The AI model returns structured parameters: person values (age, sex,
   ancestry, build), feature values, hair, beard, eyes and accessories.
3. The renderer blends the matching MakeHuman morph targets, picks the photo skin
   for that age, sex and ancestry, and fits hair and accessories to the new shape
   — all live in the viewport.
4. Blender handles final renders and file exports on demand.

**AI models.** Groq is the default provider (`openai/gpt-oss-120b`). If that model
hits a rate or size limit, the backend retries automatically with
`qwen/qwen3.8-27b` and then `openai/gpt-oss-20b`. When reference photos are
attached, a vision-capable model is used. Google Gemini can be selected instead
from the model dropdown.

---

## Requirements

| Software | Version | Used for |
|---|---|---|
| Node.js | 18 or newer | The Electron desktop app |
| Python | 3.10 or newer | The backend server |
| Blender | 3.6 – 5.x | Renders and OBJ / FBX / GLB export (optional for everything else) |
| Git LFS | any | Downloading the 3D models when cloning |
| Groq API key | free tier works | AI face building and voice input |
| Gemini API key | optional | Alternative AI provider |

Get a Groq key at <https://console.groq.com/keys> and a Gemini key at
<https://aistudio.google.com/apikey>.

---

## Installation

```bash
# 1. Clone (Git LFS fetches the 3D models)
git lfs install
git clone https://github.com/Hackfest-X-Saividya/lowcortisol-t1-05.git
cd "lowcortisol-t1-05/3D MODEL"

# 2. Frontend
npm install

# 3. Backend
pip install -r backend/requirements.txt
```

**Blender.** Install it from <https://www.blender.org/download/>, or on Windows:

```powershell
winget install --id BlenderFoundation.Blender -e
```

The backend finds Blender automatically in its standard install folders. If it is
installed elsewhere, set `BLENDER_PATH` in `.env` (see below).

---

## Configuration

Copy the example file and add your keys:

```bash
cp .env.example .env        # Windows: copy .env.example .env
```

| Variable | Required | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | yes (for Groq) | — | Groq key — AI face building and Whisper voice input |
| `GEMINI_API_KEY` | no | — | Google Gemini key, if you want to use Gemini |
| `AI_PROVIDER` | no | `groq` | Default provider: `groq` or `gemini` |
| `GROQ_MODEL` | no | `openai/gpt-oss-120b` | Main Groq model |
| `GROQ_VISION_MODEL` | no | `qwen/qwen3.8-27b` | Groq model used when photos are attached |
| `GROQ_FALLBACK_MODELS` | no | `qwen/qwen3.8-27b,openai/gpt-oss-20b` | Tried in order when the main model is rate-limited |
| `GROQ_WHISPER_MODEL` | no | `whisper-large-v3-turbo` | Voice transcription model |
| `GEMINI_MODEL` | no | `gemini-flash-latest` | Gemini model |
| `BLENDER_PATH` | no | auto-detected | Full path to `blender.exe` / `blender` |

`.env` is listed in `.gitignore` — never commit your keys.

---

## Running the app

**One command** — the app starts the backend for you:

```bash
npm start
```

**Two terminals** — useful for watching backend logs:

```bash
# Terminal 1 — backend (ready when it prints "Running on http://127.0.0.1:5001")
python backend/server.py

# Terminal 2 — desktop app
npm start
```

When the backend starts it prints whether Blender was found and which AI
providers are ready.

---

## Using Nishaan

1. **Case setup.** Enter the case number, name, investigator and notes.
2. **Describe a face.** Continue to the editor and open the **AI** tab. Type a
   description, or press the microphone, speak, press it again, review the text and
   send. Examples:
   - *"A South Asian woman in her late 50s, round full face, heavy under-eye bags,
     long dark hair"*
   - *"Young Black man with cornrows and a goatee"*
   - *"White man around 35, gaunt face, hooked nose, deep-set eyes, cleft chin,
     short brown hair, full beard"*
3. **Refine.** Send follow-ups to the AI, or adjust anything by hand:

   | Tab | What it controls |
   |---|---|
   | **Face** | Person (age, sex, ancestry, build) and every facial feature |
   | **Hair** | Hairstyle, beard, moustache, eyebrows — style, colour, tint, placement |
   | **Look** | Eyes, eyelashes, skin tone and texture, lips, painting tools |
   | **Accs** | Glasses, face masks, earrings, bandana, eyebrow ring |
   | **AI** | AI Face Builder chat, voice input, Build with a witness |
   | **Snaps** | Saved snapshots of face states |
   | **Case** | Case details, save / load / new case |

4. **Narrow down with the witness.** Press **Build with a witness**, let the
   witness pick the closest face each round, and accept the result.
5. **Inspect.** Use the viewport toolbar for front / side / 3/4 / top views,
   lighting presets, wireframe, point editing, marks, decals and head tracking.
   Undo and redo are always available.
6. **Save and share.** Save the case, render it through Blender, export a mesh, or
   take screenshots and turntable clips.

---

## Testing

There is no automated test suite. These checks cover the main paths.

**Backend** (with `python backend/server.py` running):

```powershell
# Health — blender_available should be True
Invoke-RestMethod http://127.0.0.1:5001/api/health

# AI providers — groq (and gemini, if configured) should be available
(Invoke-RestMethod http://127.0.0.1:5001/api/ai/providers).providers | Format-List

# AI face generation
$body = @{ prompt = "middle-aged man, narrow jaw, thin nose, short grey hair"; provider = "groq" } | ConvertTo-Json
(Invoke-RestMethod http://127.0.0.1:5001/api/ai/generate -Method Post -ContentType "application/json" -Body $body).params.morphTargets

# Blender render (PNG appears in backend/renders/)
Invoke-RestMethod http://127.0.0.1:5001/api/render -Method Post -ContentType "application/json" -Body '{"hairStyle":"hair1"}'

# Mesh export (file appears in backend/exports/)
Invoke-RestMethod http://127.0.0.1:5001/api/export -Method Post -ContentType "application/json" -Body '{"format":"glb"}'
```

On macOS / Linux, use `curl` with the same URLs and JSON bodies.

**Frontend**

```bash
python scripts/verify_html.py      # page structure check — expects "0 FAIL"
```

Then in the app: generate a face from a description, try voice input, move the
**Person** sliders, switch hairstyles, beards and glasses, and save a case.

---

## Backend API

All endpoints are served by `backend/server.py` on `http://127.0.0.1:5001`.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Server status and Blender detection |
| GET | `/api/ai/providers` | Which AI providers have keys configured |
| POST | `/api/ai/generate` | Description (+ optional photos, current face, history) → face parameters |
| POST | `/api/ai/variants` | Several candidate faces for the witness picker |
| POST | `/api/speech/transcribe` | Recorded audio → text (Groq Whisper) |
| POST | `/api/render` | Render the current face with Blender |
| POST | `/api/render/upload-mesh` | Upload the morphed head used for rendering |
| GET | `/api/render/download/<file>` | Download a render |
| POST | `/api/export` | Export the head as OBJ, FBX or GLB |
| GET | `/api/export/download/<file>` | Download an export |
| POST | `/api/morph` | Apply morph values to the mesh in Blender |
| POST | `/api/hair/generate` | Generate hair geometry in Blender |
| GET | `/api/hair/download/<file>` | Download generated hair |
| POST | `/api/decal/bake` | Bake decals into a texture |
| POST | `/api/case/save` | Save a case file |
| POST | `/api/case/load` | Load a case file |
| POST | `/api/blender/config` | Set the Blender executable path at runtime |

---

## Project structure

```text
3D MODEL/
├── src/
│   ├── main/                     Electron main process and preload bridge
│   └── renderer/
│       ├── index.html            App screens (case setup → method → editor)
│       ├── js/                   Viewport, morphing, hair, eyes, skin, accessories,
│       │                         AI chat, witness picker, cases, theme
│       ├── js/vendor/            Three.js loaders and orbit controls
│       ├── styles/               Layout, panels, controls and the evidence-wall theme
│       └── fonts/                Bundled fonts (Special Elite, Kalam, JetBrains Mono)
├── backend/
│   ├── server.py                 Flask API: AI, voice, render, export, cases
│   ├── analyze_mesh.py           Regenerates head region data
│   ├── blender_scripts/          Headless Blender jobs (render, export, morphs, hair, decals)
│   └── requirements.txt
├── assets/
│   ├── models/base/              Head mesh, region data, morph-target data
│   ├── models/hair/              Hairstyles and their strand textures
│   ├── models/facial/            Eyes, eyebrows, eyelashes, beards, moustache
│   ├── models/skins/             Photo skins by age, sex and ancestry
│   ├── models/face_mask/         Face masks
│   ├── accessories/              Bandana, earrings, eyebrow ring
│   ├── Glasses/                  Glasses frames and lenses
│   └── Hair_Previews/            Hairstyle preview clips
├── scripts/assets/               Pipeline that rebuilds the 3D assets from MakeHuman
├── .env.example                  Configuration template
└── package.json
```

---

## 3D assets

The head, hairstyles, beards, eyes, eyebrows, eyelashes, glasses, skin textures
and morph targets are built from [MakeHuman](http://www.makehumancommunity.org)
assets using Blender and the [MPFB](https://extensions.blender.org/add-ons/mpfb/)
add-on. Everything is generated in one coordinate frame, so hair, beards and
glasses are pre-fitted to the head and follow its shape as it changes.

To rebuild or extend the assets — for example to add a new hairstyle — follow
[scripts/assets/README.md](scripts/assets/README.md). The pipeline is:

1. `mh_build.py` (in Blender) — builds the head, fits every asset, and measures each
   MakeHuman morph target on the head.
2. `fit.py` — splits glasses lenses and computes placement values.
3. `mh_textures.py` — converts skins, eye, hair and brow textures.
4. `pack_morphs.py` — packs the morph targets into `head_morphs.json` / `.bin`.
5. `render_previews.py` (optional, in Blender) — renders the hairstyle preview clips.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| App says the backend is offline | Start `python backend/server.py` and check it prints `Running on http://127.0.0.1:5001`. Make sure nothing else uses port 5001. |
| `Groq API error: 429` or `413` | Groq's free tier limits tokens per day and per minute. The backend already falls back to other models; wait for the limit to reset, choose Gemini in the model dropdown, or upgrade your Groq plan. |
| "Groq API key not set" | Add `GROQ_API_KEY` to `.env` and restart the backend. |
| Voice input does nothing | Allow microphone access for desktop apps in your OS privacy settings, and check `GROQ_API_KEY` is set. |
| Renders or exports fail | Install Blender, or set `BLENDER_PATH` in `.env`. Check `/api/health` reports `blender_available: true`. |
| Head shows as a plain shape / models missing | The 3D models are stored with Git LFS. Run `git lfs install` and `git lfs pull` in the project folder. |
| Changes to `.env` are ignored | Restart the backend — it reads `.env` only at startup. |

---

## Credits

- **3D models, textures and morph targets:** MakeHuman and community asset authors.
  Most assets are CC0; some are CC-BY 4.0 and require attribution. The full list of
  files, authors and licenses is in
  [assets/models/CREDITS.md](assets/models/CREDITS.md) — keep it with any
  redistribution of the app or its models.
- **Fonts:** Special Elite, Kalam and JetBrains Mono (SIL Open Font License).
- **Libraries:** Electron, Three.js, Flask, Groq and Google GenAI SDKs, Blender.

---

## Responsible use

Nishaan is intended for authorised investigative and forensic work. A face built
from a witness description is an approximation of that witness's memory, not an
identification of a person. Treat every result as an investigative aid that needs
human review and corroboration — never as evidence of identity on its own.

---

## License

Released under the ISC License (see `package.json`). Third-party assets keep their
own licenses as listed in [assets/models/CREDITS.md](assets/models/CREDITS.md).
