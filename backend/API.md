# Nishaan API guide for the frontend team

Base URL: `http://localhost:8000/api/v1`. Interactive docs: `http://localhost:8000/docs`.

Every error has one shape:

```json
{"error": {"code": "free_recall_required", "message": "...", "request_id": "a1b2c3"}}
```

Long operations return **202** with a `job_id`. Poll `GET /jobs/{job_id}` or listen on the
session WebSocket. In `JOBS_INLINE=true` deployments (tests) the job is already finished when
the 202 arrives.

## Authentication

| Who | How |
|---|---|
| Staff (officer, artist, supervisor, admin) | `POST /auth/login` -> `Authorization: Bearer <access_token>` (15 min). Refresh with `POST /auth/refresh`, revoke with `POST /auth/logout`. |
| Witness | The witness token returned once by `POST /cases/{id}/sessions`, sent as `Authorization: Bearer <witness_token>` (or `X-Witness-Token`). Valid for `WITNESS_TOKEN_TTL_MIN` or until sign-off. |

The witness token can only: submit statements and answers, get the next question, view
sketch images (never the photoreal master), submit edits, set locks and confidence, rate
versions, patch the scene, report display events and sign off.

## Main flow

1. **Login** `POST /auth/login {"username","password"}`
2. **Case** `POST /cases {"case_number","crime_type","location_text","occurred_at"}`
3. **Witness** `POST /cases/{case_id}/witnesses {"display_name","preferred_language":"kn","consent_given":true,"consent_note"}`
   Consent is required before a session can start.
4. **Session** `POST /cases/{case_id}/sessions {"witness_id"}` -> `{"session": {...}, "witness_token": "..."}`.
   Give the token to the witness device. Open the WebSocket `ws://host/ws/sessions/{id}?token=...`.
5. **Free recall** (required before any face is shown):
   - JSON text: `POST /sessions/{id}/statements {"text","language":"hi|kn|en","kind":"free_recall","source":"typed|browser_asr"}`
   - Audio: `multipart/form-data` with `audio` (webm/ogg/wav/mp3/m4a, <= 20 MB) and form fields `language`, `kind`.
   Returns `202 {"statement_id","job_id"}`. Events: `statement.transcribed`, `feature_sheet.updated`.
   Read back with `GET /sessions/{id}/statements/{statement_id}`; corrections via `PATCH` (staff) re-run extraction.
6. **Feature sheet** `GET /sessions/{id}/feature-sheet` -> `{"sheet": {field: {value, confidence, source_text, source, updated_at}}}`.
7. **Interview**: `GET /sessions/{id}/questions/next` ->
   `{"done": false, "question": {"id","field_key","stage","text_en","text_local","options":[{"id","label","field","value"}], ...}}`
   Options are feature-card ids (draw them from `GET /feature-cards`); `not_remembered` is always present.
   Answer with `POST /sessions/{id}/questions/{qid}/answer {"answer_type":"option|text|voice|not_remembered|skipped","option_id","text","language"}`.
   Voice answers can also be uploaded as audio statements with `kind=answer_audio` and `question_id`.
   `{"done": true, "reason": "complete|limit"}` ends the interview (hard stop after 12 questions).
8. **First face** `POST /sessions/{id}/sketch {"seed": optional}` -> 202 (409 `free_recall_required` otherwise).
   Event `version.created` carries `version_id` and `sketch_file_id`.
9. **Show the sketch** `GET /files/{sketch_file_id}` (PNG). Report it with
   `POST /sessions/{id}/display-events {"sketch_version_id","screen":"witness"}` every time an image is shown.
10. **Edit** `POST /sketch-versions/{vid}/edits` (body below) -> 202. Job result:
    ```json
    {"status":"created","new_version_id":"...","parent_version_id":"...","sketch_file_id":"...",
     "stability":{"locked_drift_px":0.0,"ssim_outside_mask":0.998,"geometry_similarity":0.97,"warning":false,"reasons":[]},
     "provider_info":{"type":"geometric","provider":"local"}}
    ```
    Other results: `{"status":"needs_choice","previews":[{"amount":0.05,"sketch_file_id"},...]}` (show three
    previews, then resend the edit with the chosen `amount`), `{"status":"refused","message":"The jaw is locked. Unlock it first."}`,
    `{"status":"unknown","message":...}`.
11. **Locks and confidence** `GET/PUT /sessions/{id}/locks {"locks":[{"feature":"eyes","locked":true,"confidence":"sure"}]}`.
    Features: face_shape, eyes, brows, nose, mouth, jaw, hair, ears, skin, marks.
12. **Tree and compare** `GET /sessions/{id}/sketch-tree`, `GET /sketch-versions/{vid}`,
    `GET /sketch-versions/{a}/compare/{b}`, `POST /sketch-versions/{vid}/rating {"rating":"closer|further"}`.
13. **Scene** `POST /sessions/{id}/scene {"template": optional}` -> 202; `GET /scene-versions/{vid}` (includes
    `analysis: {distance_m, line_of_sight, blocking_object_id}`); `POST /scene-versions/{vid}/patches {"patch":[RFC 6902 ops],"source":"drag"}`
    (synchronous, returns the new version, 422 `object_locked` if a locked object changes);
    `POST /scene-versions/{vid}/commands {"utterance_original","language"}` -> 202; `GET /sessions/{id}/scene-tree`; `GET /scene-templates`.
14. **Sign-off** `POST /sessions/{id}/signoff {"sketch_version_id","scene_version_id","confidences":{"eyes":"sure"},"witness_statement"}`.
    The session becomes `signed_off` and the witness token stops working.
15. **Export** (staff) `POST /sessions/{id}/exports {"kind":"png|pdf|scene_png|photoreal_png"}` -> 202, event `export.ready`;
    `GET /exports/{id}`; download via `GET /files/{file_id}` (`X-File-SHA256` header).
16. **Audit** `GET /audit?session_id=&case_id=&action=&cursor=&limit=` (officer: own cases, supervisor: jurisdiction);
    `POST /audit/verify` (supervisor, admin).

## Added for the frontend

- `GET /sessions/{id}/statements` and `GET /sessions/{id}/questions`: full lists in time order
  (witness: own session; staff: case scope). Used by the incident timeline and the session desk.
- `POST /sessions/{id}/witness-token` (assigned officer, open session): issues a new witness code
  and invalidates the old one, so the witness window can be reopened later.
- `GET /sessions/{id}` now also returns `preferred_language` (the witness's language).

## Live voice interview (witness window)

- `GET /sessions/{id}/interview/live` -> `{started, language, question_local, question_en, ask_field, sheet, adjust}`.
  Before the first answer the question is the free-recall opening.
- `POST /sessions/{id}/interview/turn` with JSON `{"text", "language", "source": "typed", "dont_remember": false}`
  or multipart `audio` (+ `language`) for Whisper (what the witness window sends). One call per witness turn (one LLM request):
  returns `{transcript_original, transcript_english, updated_fields, adjustments, sheet, adjust,
  reply_local, reply_en, ask_field, done}`. `reply_local` is the artist's next spoken question
  (direct, open, never multiple choice); `adjust` holds cumulative drawing corrections
  (`jaw_width`, `nose_length`, ... as fractions of face width); `done` means review mode.
- `POST /tts {"text", "language"}` -> `audio/wav` (Gemini speech) or `204` when unavailable; the
  browser uses its own voice first and calls this only when it has none for the language.
- `POST /sessions/{id}/transcribe` multipart `audio` (+ `language`) -> `{text, provider}`: the words
  so far while the witness is still talking (Groq Whisper, about 1 s). Not stored; audited as
  `transcribe.interim`. The final answer is still sent as audio to `/interview/turn`.
- `POST /sessions/{id}/interview/render` JSON `{"text"?, "commit": false, "wait_s"?}` -> the live
  forensic pencil sketch as two layers, `{ready, kind, pending, seq, version_id, lines_b64,
  sketch_b64, provider, preview_fields}` (JPEG base64, 768 px).
  - `text` = words still being spoken: face details are extracted into a copy of the description
    (nothing stored) and drawn at once.
  - `kind = "instant"`: the closest face from the base-face library (gender, age, facial hair)
    with the spoken corrections applied as smooth warps and spectacles/headwear overlays (about
    0.2 s, no network).
  - `kind = "portrait"`: a realistic portrait generated from the whole description (Workers AI,
    then Pollinations), made in the background, one at a time per session, always for the newest
    description. `pending = true` means one is on its way.
  - `commit = true` saves what is shown as a sketch version (`edit.type = "live"`,
    `edit.render = instant|portrait`, deduplicated); it waits up to `wait_s` (default 30 s) for
    the portrait first. Audited as `sketch.live_render`.
  - `{ready: false, reason: "not_enough_detail"}` until a face detail is known.
- `GET /sessions/{id}/interview/render/latest?after=<seq>` -> the newest finished portrait if its
  `seq` is newer than `after`, plus `pending` (poll every 1.5 s while `pending`).
- `POST /sessions/{id}/sketch/live` multipart `image` (PNG) + `params` (JSON): saves an image as a
  live sketch version (kept for compatibility; the witness window now uses `interview/render`).

## Edit body

```json
{
  "source": "voice | text | drag | slider | accessory | artist",
  "utterance_original": "jabda thoda chauda karo",
  "language": "hi",
  "edit": {
    "region": "jaw",
    "type": "geometric | overlay | inpaint",
    "param": "jaw_width",
    "amount": 0.05,
    "handle_moves": [{"handle": "jaw_left", "dx": -0.01, "dy": 0.0}],
    "overlay_id": "spectacles_round",
    "overlay_params": {"position": "left_cheek", "size": 1.0, "remove": false},
    "prompt": "short grey hair",
    "symmetric": true
  }
}
```

- Omit `edit` to let the edit router interpret the utterance (amount words: a little / thoda / swalpa = 0.05,
  more / aur / innu = 0.10, a lot / bahut / tumba = 0.15).
- `amount`, `dx`, `dy` are fractions of the face width (distance between landmarks 234 and 454). Negative = smaller/narrower.
- Sliders: `jaw_width, face_length, eye_size, eye_spacing, nose_length, nose_width, lip_fullness, brow_height`.
  `GET /sketch-controls` returns the handle list (name, anchor landmark, region, mirror) and slider definitions.
- `GET /sketch-versions/{vid}` returns 478 normalized landmarks plus `handle_positions` for drawing drag handles.
  Side naming follows MediaPipe: "left" is the subject's left (image right).
- Overlays: `GET /overlays` lists ids, names, regions and thumbnails; scar, mole and tilak take `position`
  (`left_cheek | right_cheek | forehead | chin`) and `size`.
- Inpaint edits need an online provider; otherwise the job fails with
  "This change needs online image editing, which is unavailable. Try a shape edit or an accessory instead."

## WebSocket events

`/ws/sessions/{id}?token=...` sends JSON `{"type", "session_id", "at", "data"}` with types
`statement.transcribed`, `feature_sheet.updated`, `question.next`, `job.progress`, `version.created`,
`stability.result`, `preview.ready`, `scene.updated`, `export.ready`, `error`. Send `ping` to get `pong`.

## Health

`GET /health` -> `{"status":"ok"}`. `GET /ready` -> database state, provider status, fallback chains and
`data_mode` (`cloud_demo` or `local_mock`).
