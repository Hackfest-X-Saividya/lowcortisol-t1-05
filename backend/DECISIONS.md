# Decisions log

Deviations from the brief and choices made where it was ambiguous or where provider
details had changed. Numbered in the order they were taken.

1. **Python version.** The brief asks for Python 3.11. The developer's laptop has 3.13 and
   MediaPipe 1.2.0 ships wheels for 3.9 to 3.14, so `requires-python` is `>=3.11` and the venv
   uses the installed 3.13. No 3.12+ language features are used.
2. **OpenCV distribution.** MediaPipe declares a hard dependency on `opencv-contrib-python`.
   Installing `opencv-python-headless` next to it would leave two competing `cv2` packages, so
   the project depends on MediaPipe and uses the `cv2` it brings. Only core functions are used.
3. **MediaPipe 1.x API.** MediaPipe 1.2.0 re-implemented the Python Tasks layer on ctypes, but
   `FaceLandmarker.create_from_options(...).detect(mp.Image)` and the
   `FaceLandmarksConnections.FACE_LANDMARKS_*` lists (now including `NOSE`) are unchanged.
   `services/sketch/regions.py` builds every region from those lists; jaw and cheekbone
   sub-regions are derived from the face oval using the template geometry.
4. **Canonical face template.** `assets/templates/canonical_face.json` holds 478 landmarks
   detected by MediaPipe on the synthetic OpenCV reference face (the same drawing the mock
   image provider produces). Alignment maps the eye centres and mouth centre of generated
   faces onto its targets; in mock mode the template landmarks are used directly.
5. **Model names (verified 2026-10-28).** `gemini-2.5-flash` is still listed by the API but
   returns 404 for `generateContent`; `llama-3.3-70b-versatile` no longer exists on Groq.
   Defaults are now `GEMINI_MODEL=gemini-3.5-flash` and `GROQ_LLM_MODEL=openai/gpt-oss-120b`
   (both tested with JSON mode). `whisper-large-v3`, `@cf/bytedance/stable-diffusion-xl-lightning`
   and Pollinations all answered the smoke test.
6. **Gemini response schema.** `response_schema` is passed only for small flat models
   (translation, question phrasing, leading check). Dict-shaped outputs (feature sheet, edit
   spec, scene, patch) use JSON mime type plus prompt instructions and are validated with
   Pydantic afterwards; on failure the request is retried once with the validation error and
   then falls back to the next provider.
7. **Cloudflare inpainting inputs.** `@cf/runwayml/stable-diffusion-v1-5-inpainting` is called
   with `prompt`, `image_b64` (base64 PNG) and `mask` as an array of the mask PNG's bytes
   (the documented input form), plus `width`/`height` 512 and `strength`. Responses are
   decoded from either raw image bytes or `{"result": {"image": base64}}` by Content-Type.
8. **Transactions.** SQLite connections run in autocommit mode; reads never hold a snapshot.
   `app.db.session.commit_tx` and `app.core.audit.commit_with_audit` open `BEGIN IMMEDIATE`
   right before flushing and commit immediately after, under a module-level `asyncio.Lock`
   for audited writes. This keeps the audit row atomic with the business change while letting
   a request await background jobs (or the provider cache) without deadlocking on the writer
   lock. Repositories therefore never flush early; string UUID ids are assigned at object
   construction (SQLAlchemy `init` event).
9. **Audit hash input.** The hashed entry excludes the integer `id` (assigned by the database
   at insert) as well as `prev_hash`/`hash`; ordering is protected by the chain itself.
10. **Reads are audited.** Case/session/version/file/export/audit views each write an audit
    entry, which means almost every request is a write; the audit log is the busiest table.
11. **Witness `left`/`right`.** Side names follow MediaPipe: "left" is the subject's left,
    which appears on the image's right. Handles (`jaw_left` = landmark 397) and positional
    overlays (`left_cheek` = landmark 280) use the same convention; documented in `API.md`.
12. **Feature locks and accessories.** Locks protect face geometry (warps and inpainting).
    Accessory overlays never move landmarks, so they are allowed on locked regions; only the
    `marks` lock blocks scar/mole/tilak overlays. This is required for the brief's own flow
    (lock eyes, then add spectacles).
13. **Warp speed.** The piecewise-affine warp builds an inverse map at `WARP_INTERNAL_PX`
    (512) over the Delaunay triangulation of 478 landmarks + 8 border points, upscales the
    *displacement* field and applies one `cv2.remap` at full resolution. A 1024 px jaw edit
    takes about 50 ms on the laptop. Unmoved triangles map to the identity exactly, which is
    what makes locked regions pixel-identical.
14. **Edit mask for warps.** The stored mask is the region hull plus every pixel the warp
    actually displaced (minus locked regions); otherwise SSIM "outside the mask" would be
    penalised by the warp's own falloff around the hull.
15. **Inpainting keeps landmarks.** After an inpaint edit the parent's landmarks are kept
    (hair/skin/texture changes do not move features). Cloud mode could re-detect, but a
    detection jitter would show up as false drift.
16. **Sketch versions store extra columns.** `base_master_file_id` (face without overlays),
    `overlays` (list re-applied after each warp) and `sliders` (cumulative slider values) were
    added to `sketch_versions` beyond the brief's column list so the version endpoint can
    return slider values and overlays and shape edits never distort accessories.
17. **Statements carry `target_version_id`.** Audio edit and scene commands name the version
    they apply to (brief section 12), so the column was added to `statements`.
18. **Scene locks.** A patch that changes a locked object is rejected, except a patch whose
    only effect on that object is its `locked` flag (explicit unlock by the officer).
19. **Line of sight.** The ray runs from the witness's eye (`eye_height_m`, default 1.5 m) to
    the suspect's head at 1.3 m as specified, tested against each object's rotated box
    (floor OBB x height) and the room boundary (a wall blocks when one person is outside).
    A standard 1.0 m counter therefore does not block the view; tests use a taller object.
20. **Scene JSON from LLMs is coerced.** A lenient pre-validator accepts common variations
    (string events, `{"x","z"}` positions, 2-vectors, free-text roles) before strict validation.
21. **PDF text shaping.** ReportLab draws Devanagari and Kannada glyphs with the Noto fonts
    but without complex-script shaping, so conjuncts may look unshaped. The exact original
    transcript is preserved in the database and API; a shaping engine would be a later upgrade.
22. **Rate limit headers.** slowapi header injection is disabled (`headers_enabled=False`)
    because it requires a `response` parameter on the route; the 429 body and `Retry-After`
    header are produced by our own handler.
23. **Coverage core.** `pyproject.toml` sets `core = "sysmon"` for coverage; the default C
    tracer silently drops lines executed under SQLAlchemy's greenlet bridge and reported
    23% for code that the integration tests fully exercise.
24. **Interview stages.** Accessory and clothing fields are asked in the `marks` stage after
    scars/moles/tattoos (the brief lists situation, overall, face, marks, check). Scene fields
    are extracted from free recall but never asked by the sketch interview.
25. **Job results carry refusals.** A refused or unrecognised edit is a successfully finished
    job whose result has `status: refused|unknown` and a friendly message (plus an `error`
    WebSocket event); a failed job is reserved for provider or internal errors.
26. **Endpoints added for the frontend.** List endpoints for a session's statements and
    questions (the witness timeline and the officer desk need them), a witness-code reissue
    endpoint (the one-time code could otherwise never be recovered when an officer reopens a
    session), and `preferred_language` on the session detail so the witness window picks its
    language without reading the case file. All are audited like every other read and write.
27. **Live voice interview replaces the multiple-choice witness flow.** The witness speaks;
    the browser records the microphone and a level meter detects speech and the pause that ends
    an answer (about 1.7 s). While they talk, the audio so far goes to Groq Whisper every ~2 s
    (`POST /transcribe`, about 1 s) so the words appear on screen; the final recording is the
    turn. The browser Web Speech API was dropped: it has no Kannada in most browsers and failed
    silently, which left the interview stuck on "nothing heard". Each answer is one backend call
    that translates, extracts details, interprets drawing corrections and phrases the next open
    question in a single LLM request. The deterministic engine still chooses the field, the
    leading-question rule check still guards the wording (unsafe wording falls back to fixed
    Kannada/Hindi/English templates), and every question and answer is stored and audited as
    before. The interviewer's voice is the browser's own voice for the language when available,
    otherwise Gemini TTS via `/tts` (skipped after 5 s; the question stays on screen).
28. **Face first in the live interview.** The live order is overall -> face -> marks ->
    situation (light, distance, time, angle are asked last) so the drawing starts at once;
    the limit is `INTERVIEW_LIVE_MAX_QUESTIONS` (24).
29. **The witness-facing sketch is a realistic forensic pencil composite, drawn while they
    talk.** (Replaces the earlier cartoon-style parametric drawing, which was not usable for
    identification.) Every few new words, `POST /interview/render {text}` redraws the face:
    - at once (about 0.2 s, local) from a base-face library of 12 AI-generated frontal
      portraits (`assets/base_faces`, made by `scripts/make_base_faces.py`; male young/middle/
      older x clean/moustache/beard, female young/middle/older; no real people);
    - then, in the background, a realistic portrait generated from the full description
      (`realistic_prompt`, fixed per-session seed where the model takes one), which replaces it.
    Spoken corrections are applied as smooth Gaussian displacement fields on MediaPipe landmarks
    (`live_warp.py`); each push is capped at 0.8 x its radius so the face can never tear or fold
    (the slider mesh warp summed several handles per eye and folded on live amounts). The
    browser shows the outlines first, sweeping down the sheet, then lays in the graphite
    shading, with the previous drawing fading like erased graphite. Every drawing the witness
    saw at the end of a turn is saved as a sketch version (instant now, the portrait again when
    it arrives); Finish waits up to 25 s for the portrait. The pencil render was fixed for dark
    hair (uint8 colour-dodge divide-by-zero and JPEG-noise edges made black blocks) and gets a
    levels stretch so darks read like graphite.
30. **Latency and free-tier limits (measured 2026-10-28).**
    - LLM: Groq is primary (`openai/gpt-oss-120b`, `reasoning_effort=low`, about 1-1.5 s);
      Gemini quota on the demo key was exhausted. Groq rate limits are per model, so a 429 moves
      to `GROQ_LLM_FALLBACK_MODEL` (`openai/gpt-oss-20b`, about 0.7 s) at once and skips the
      limited model for a minute. (`llama-3.3-70b-versatile` is not available on this key.)
    - Live preview extraction (`quick_fields`) asks only for face fields the words mention; the
      first version returned every field as text, wasted tokens and hit the rate limit.
    - Images: Cloudflare's free allowance is 10,000 neurons a day for the whole account. Leonardo
      Lucid Origin is the most realistic but costs about 3,000 neurons per 1024 px portrait, so it
      used the day up in a few renders. Default is now `@cf/black-forest-labs/flux-1-schnell`
      (about 60 neurons, ~2 s, realistic; it takes no seed) with SDXL base as the in-account
      fallback. A "daily free allocation" 429 cools Cloudflare until the next UTC midnight and
      skips the second Workers AI model (same allowance).
    - Pollinations (no key) answers in 8-120 s depending on its queue and stamps a logo
      (`nologo` is ignored without a key): the bottom 7% is cropped, negative prompts are not
      sent (it reads "avoid glasses" as "glasses"), `POLLINATIONS_TIMEOUT_S=45`. This is why the
      instant library drawing exists.
    - A 429 is never retried with backoff; the registry falls back at once and cools the
      provider for `PROVIDER_COOLDOWN_S` (300 s).
    - Measured in the browser with the real providers: first words on screen and first pencil
      drawing within about 5 s of the witness starting to talk; a turn (Whisper + LLM) 1.5-3 s.
31. **Frontend paint cost.** The SVG turbulence "ink" filter on text and the double drop-shadow
    on every paper were the main paint costs; replaced by a text-shadow bleed and a single shadow.
    The board re-measures pins only on real layout changes (no polling), and the landing torch
    moves a pre-painted layer with `transform` instead of repainting the screen per mouse move.
