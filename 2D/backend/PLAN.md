# Nishaan backend — build plan

Light build: CPU-only laptop, SQLite, in-process jobs, free-tier cloud AI behind
provider interfaces with deterministic mocks. Everything lives in `backend/`.

## Architecture in one paragraph

FastAPI routes (`app/api/v1`) do no business logic. They call services
(`app/services`) which use repositories (`app/db/repositories`) and providers
(`app/providers`). Long work (transcription, extraction, sketch generation,
edits, scene build, exports) runs through an in-process job runner
(`app/core/jobs.py`) that writes a `jobs` row and publishes progress on an async
event bus (`app/core/events.py`) consumed by the per-session WebSocket. Every
business write and every sensitive read goes through the hash-chained audit
writer (`app/core/audit.py`) inside the same transaction. Files are AES-256-GCM
encrypted at rest (`app/core/crypto.py`, `app/services/storage.py`) and served
only via `/files/{id}`.

## Milestones

- [x] 1. Skeleton: config (safe .env loading), logging, errors, health, `.env.example`, `.gitignore`
- [x] 2. Database models, Alembic migration, audit triggers, seed script
- [x] 3. Auth, RBAC, witness tokens, audit writer/verifier, encrypted file store
- [x] 4. Cases, witnesses, sessions, display events, job runner, event bus, WebSocket
- [x] 5. Provider interfaces, mocks, provider cache, Gemini/Groq/Cloudflare/Pollinations clients with fallback, `smoke_test_providers.py`
- [x] 6. Statements, transcription, translation, feature extraction
- [x] 7. Interview engine and leading-question check
- [x] 8. Sketch pipeline: generation, face check, alignment, landmarks, regions, handles, sliders, warp, masks, overlays, edit router, previews, inpainting, compositing, stability, rendering, version tree, locks, compare
- [x] 9. Scene: schema, templates, builder, patches, commands, geometry, version tree
- [x] 10. Sign-off, exports (PNG, PDF), files endpoint
- [x] 11. Tests to target, README.md, API.md, DECISIONS.md

After each milestone: `ruff check .`, `mypy app`, `pytest`.
