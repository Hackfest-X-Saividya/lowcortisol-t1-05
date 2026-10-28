# Nishaan frontend

React 18 + Vite, plain CSS, no UI or icon libraries. Every screen is the same evidence wall:
a dark felt wall, torn manila paper, red string between glossy red pins. Red is the only
accent; selected, active and warning states are all shown in red.

## Run

```bash
# 1. backend (from backend/)
uvicorn app.main:app --reload            # http://localhost:8000

# 2. frontend (from frontend/)
npm install
npm run dev                              # http://localhost:5173
```

The dev server proxies `/api` and `/ws` to the backend, so no CORS setup is needed. To point
it at another backend: `NISHAAN_BACKEND=http://localhost:8002 npm run dev`.
`npm run build` writes a static build to `dist/` (serve it behind the same `/api` and `/ws`
proxy).

## Screens

| Route | Who | What |
|---|---|---|
| `/` | everyone | Landing page: the evidence wall, wordmark, one line, Enter |
| `/app` | staff | Sign in |
| `/app/cases` | officer, supervisor, artist | Case files; officers open new cases |
| `/app/cases/:id` | staff on the case | Case details, witnesses with consent, start session, witness code |
| `/app/sessions/:id` | staff on the case | Session desk: summary, statements (correct transcripts), interview, feature sheet, sketch versions (staff-only photo toggle), scene with line-of-sight, exports, audit log |
| `/app/admin` | admin | Users, unlock/deactivate, audit chain check |
| `/witness/:sessionId` | witness | Witness window (Kannada / Hindi / English by the witness's language) |

### Witness window: a live interview with a sketch artist

1. **Start interview.** The artist's opening question appears on the notepad and is spoken
   aloud (the browser's voice for Kannada/Hindi/English, or Gemini speech from the backend).
2. **The witness talks.** The microphone is recorded; a red bar follows their voice so they can
   see it is heard. Their words appear on screen every couple of seconds (Groq Whisper on the
   backend), in any browser. A pause of about two seconds ends the answer, or they press
   "I have finished speaking". "Type instead" works too.
3. **The sketch is drawn while they talk.** Every few new words the face is redrawn: a realistic
   forensic pencil composite, outlines first (sweeping down the sheet), then the graphite
   shading. The first drawing comes at once from the closest stock face; a portrait generated
   from the whole description replaces it a few seconds later ("Adding the finer details").
   The witness only ever sees pencil drawings.
4. **The artist asks the next direct question**, shown and spoken, about whatever is still
   missing (face first, viewing conditions last). No multiple choice.
5. **Corrections any time**: "make the jaw a bit wider", "nose longer", "eyes closer together",
   "he wore square glasses". The drawing reshapes and the artist confirms.
6. **Finish sketch** saves the drawing (each turn's drawing is also saved as a version); the
   artist asks how close it is; **Sign and finish**.

Needs microphone permission (on `localhost` or HTTPS). If the microphone is blocked or missing,
the typing box opens. "Voice off" mutes the artist; "Repeat question" says it again;
"I don't remember" moves on.

The left index also opens the crime scene wall (drag people and objects; say a change), the
evidentiary vault (saved sketches) and the incident timeline
(what the witness said). "Pause screen" hides everything until the witness continues.

The officer opens the witness window from the case file or the session desk ("Open witness
window" hands the one-time code to the new tab through local storage, never through the URL).
On a separate device, open `/witness/<session id>` and type the code.

## Files

```
src/
  pages/Landing.jsx          landing page (all layout computed from the viewport)
  pages/witness/             witness window + its building blocks
  pages/staff/               sign in, case files, case file, session desk, admin
  components/Board.jsx       wall, string ring, pins that strings measure and end on
  components/Paper.jsx       torn paper, strips, red stamps, square ink buttons
  components/PencilFace.jsx  pencil-style faces (landing, thumbnails, placeholders)
  components/SketchCanvas.jsx the live forensic sketch: outlines drawn, then shading laid in
  lib/useVoice.js            microphone + speech detection + live words; the artist's voice
  components/OptionThumb.jsx interview card thumbnails
  components/SceneMap.jsx    top-down scene with drag
  lib/i18n.js                witness words in Kannada, Hindi, English
  lib/api.js                 API client, job polling, protected files, WebSocket
  styles/                    tokens, wall kit, landing, witness, staff
```
