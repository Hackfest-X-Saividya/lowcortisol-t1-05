# Nishaan test console (dummy frontend)

A single static page (`index.html` + `app.js`, no build step, no dependencies) that drives
every backend endpoint so you can test the API by hand: login, case/witness/session,
statements (typed, file upload or microphone), the interview, sketch generation and edits
(utterance, slider, overlay, inpaint, previews, locks, ratings, compare), scene build /
patch / command with a top-down canvas, sign-off, exports and the audit log, plus a live
WebSocket event feed.

## Run

1. Start the backend (`cd backend && uvicorn app.main:app --reload`). Mock mode is fine:
   set `AI_MODE=mock` in `backend/.env` or the environment to stay offline.
2. Serve this folder on port 5173 (the backend's default `CORS_ORIGINS`):

   ```bash
   cd frontend-test
   python -m http.server 5173
   ```

   Opening `index.html` directly from disk will not work because of CORS.
3. Open <http://localhost:5173>, log in with a seeded user (`python -m app.seed.seed` prints
   the passwords once), then walk the numbered sections top to bottom.

## Notes

- **Act as** switches every request between the staff token and the witness token
  (filled automatically when you start a session). Use *witness* to check what the witness
  can and cannot do (for example the photoreal master file is forbidden).
- Images and exports are fetched with the auth header and shown via blob URLs, since
  `<img src>` cannot send `Authorization`.
- Long operations show the 202 job, poll `/jobs/{id}` and then show the result; the
  WebSocket panel logs `job.progress`, `version.created`, `preview.ready` and so on.
- The microphone button records `audio/webm` with `MediaRecorder` and uploads it as a
  statement of the selected kind (in mock mode the transcript is a fixture).
- The "Last response" box at the bottom always shows the most recent JSON (or error body).
