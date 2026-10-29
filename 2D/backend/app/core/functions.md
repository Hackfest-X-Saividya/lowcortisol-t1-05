# `app/core`: the backend's foundation

`app/core` holds the parts every other layer relies on: errors, logging, request ids, security
(passwords and tokens), role-based access control, file encryption, the tamper-evident audit
log, the event bus that feeds the WebSockets, and the background job runner.

None of it knows about cases, sketches or scenes. Routes (`app/api`) and services
(`app/services`) call into it, and it calls only `app.config`, `app.db` and other `core` modules.

```
request ─► middleware.py (request id, security headers)
        ─► ratelimit.py (login only)
        ─► api/deps.py ─► security.py (JWT / witness token ─► Principal)
        ─► service ─► rbac.require(principal, action, scope)
                   ─► audit.record(...) ... audit.commit_with_audit(db)
                   ─► jobs.submit(...) ─► handler runs ─► events.publish(...) ─► WebSocket
        ─► errors.py turns any exception into {"error": {...}}
```

## Tech stack

| Concern | Library | Used in |
| --- | --- | --- |
| Web framework | **FastAPI** (on Starlette), served by **uvicorn** | `errors.py`, `middleware.py`, `ratelimit.py` |
| Database | **SQLAlchemy 2 (async)** + **aiosqlite** (SQLite) | `audit.py`, `jobs.py` |
| Password hashing | **argon2-cffi** (Argon2id) | `security.py` |
| Access tokens | **PyJWT** (HS256) | `security.py` |
| File encryption | **cryptography** (AES-256-GCM + HKDF-SHA256) | `crypto.py` |
| Rate limiting | **slowapi** | `ratelimit.py` |
| Concurrency | Python **asyncio** (tasks, queues, locks), **contextvars** | `jobs.py`, `events.py`, `audit.py`, `logging.py` |
| Hashing | `hashlib` SHA-256 | `audit.py`, `security.py`, `crypto.py` |

Python 3.13. Settings (secrets, token lifetimes, `JOBS_INLINE`) come from `app/config.py`
(pydantic-settings, read from `.env`).

---

## `errors.py`: typed errors and the single error shape

Every error that leaves the API has the same JSON shape:

```json
{"error": {"code": "not_found", "message": "Case not found", "request_id": "3f9a..."}}
```

Some errors also carry a `details` object.

### Classes

| Class | HTTP | `code` | Typical use |
| --- | --- | --- | --- |
| `AppError` | 400 | `bad_request` | Base class: `message`, optional `code`/`status_code` override, `details` dict |
| `BadRequest` | 400 | `bad_request` | Malformed input that passed schema validation |
| `Unauthorized` | 401 | `unauthorized` | Missing, expired or invalid token |
| `Forbidden` | 403 | `forbidden` | RBAC denied the action |
| `NotFound` | 404 | `not_found` | Unknown id |
| `Conflict` | 409 | `conflict` | State clash (e.g. session not active) |
| `PayloadTooLarge` | 413 | `payload_too_large` | Upload over the size limit |
| `UnsupportedMedia` | 415 | `unsupported_media_type` | Wrong file type |
| `ValidationFailed` | 422 | `validation_failed` | Business validation (e.g. invalid scene JSON) |
| `Locked` | 423 | `locked` | Object is locked / signed off |
| `RateLimited` | 429 | `rate_limited` | Too many requests (adds a `Retry-After` header) |
| `ProviderError` | 502 | `provider_error` | An AI provider (Gemini, Groq, Cloudflare) failed after retries; also has `provider`, `retryable`, `status` |
| `ServiceUnavailable` | 503 | `service_unavailable` | A dependency is down |

### Functions

- **`error_body(code, message, request_id=None)`** builds the `{"error": {...}}` dict. It fills
  `request_id` from the current request's context variable when none is passed.
- **`install_error_handlers(app)`** registers four FastAPI exception handlers:
  1. `AppError`: uses the class's status and code, includes `details`, and sets `Retry-After`
     for `RateLimited`.
  2. `RequestValidationError` (pydantic rejected the request body): 422 with the field errors.
  3. Starlette `HTTPException` (404 route, 405 method...): maps the status to a code.
  4. Any other `Exception`: logs the stack trace and returns a generic 500
     `internal_error`, so internals never leak to the client.

**How it's done:** services raise typed exceptions instead of building responses. One place
turns them into HTTP, so every endpoint answers the same way.

---

## `logging.py`: logging with request-id correlation

Rule written into the module: **never log keys, tokens, transcripts or images. Log ids only.**

- **`request_id_var`** is a `contextvars.ContextVar` holding the current request id
  (default `"-"`). Context variables follow each asyncio task, so concurrent requests never
  mix up their ids.
- **`RequestIdFilter`** is a logging filter that copies `request_id_var` onto every log record.
- **`setup_logging(level)`** configures the root logger once. It writes to stdout in the format
  `time LEVEL [request_id] logger: message` and quietens noisy libraries (`httpx`, `httpcore`,
  `aiosqlite`, `sqlalchemy.engine`, `watchfiles`). Calling it again only changes the level.
- **`get_logger(name)`** is a thin wrapper over `logging.getLogger`.

---

## `middleware.py`: request id and security headers

**`RequestContextMiddleware`** (a Starlette `BaseHTTPMiddleware`) runs on every HTTP request:

1. Takes the caller's `X-Request-ID` header, or makes a 16-character id from a UUID.
2. Stores it in `request_id_var` and `request.state.request_id`, so logs, errors and audit
   entries all carry the same id.
3. Echoes `X-Request-ID` back on the response.
4. Adds security headers (unless the route already set them):
   `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
   `Cache-Control: no-store`, `Permissions-Policy: camera=(), geolocation=()` and a strict
   `Content-Security-Policy: default-src 'none'`. The CSP is skipped on `/docs` and `/redoc`
   because those pages need their scripts.

`app/main.py` installs it together with CORS.

---

## `ratelimit.py`: login rate limiting

- **`limiter`** is a slowapi `Limiter` keyed by the client IP (`get_remote_address`).
- **`install_rate_limiting(app)`** attaches the limiter to `app.state` and turns slowapi's
  `RateLimitExceeded` into the standard error body: 429 with `Retry-After: 60`.

Used as a decorator on `POST /api/v1/auth/login` (`@limiter.limit("10/minute")`) to slow down
password guessing.

---

## `security.py`: passwords, tokens and the `Principal`

### `Principal` (dataclass)

Says *who is acting*. It is built per request by `api/deps.py` and passed to every service,
RBAC check and audit entry.

| Field | Meaning |
| --- | --- |
| `kind` | `"user"` (staff), `"witness"` or `"system"` |
| `user_id`, `role` | Staff id and role: `officer`, `supervisor`, `artist`, `admin`, `witness`, `system` |
| `station`, `jurisdiction` | Used by RBAC (officers act within a station, supervisors within a jurisdiction) |
| `session_id`, `case_id` | A witness principal is bound to exactly one interview session |
| `ip`, `user_agent`, `request_id` | Request metadata copied into audit entries |
| `extra` | Free-form extras |

- `is_witness` and `is_staff` are convenience properties.
- **`Principal.system()`** is used by background work that acts as the system itself.

### Passwords (Argon2id)

- **`hash_password(password)`** hashes with Argon2id (`time_cost=2`, `memory_cost=64 MiB`,
  `parallelism=2`). The salt is random and stored inside the hash string.
- **`verify_password(hash, password)`** returns `True`/`False` and never raises on a mismatch
  or a malformed hash.

### Access tokens (JWT, HS256)

- **`create_access_token(settings, user_id, role)`** signs a short-lived JWT with
  `sub`, `role`, `type="access"`, a random `jti`, `iat` and `exp`. The lifetime is
  `JWT_ACCESS_TTL_MIN`, default 15 minutes, and the key is `JWT_SECRET`.
- **`decode_access_token(settings, token)`** checks the signature, expiry and
  `type == "access"`. It raises `Unauthorized` with code `token_expired` or `token_invalid`.

### Opaque tokens (refresh tokens and witness links)

- **`new_opaque_token(nbytes=32)`** returns a random URL-safe string (`secrets.token_urlsafe`).
- **`token_hash(token)`** returns its SHA-256 hex digest. **Only the hash is stored in the
  database**, so a leaked database cannot be replayed as tokens. On each request
  `api/deps.py` hashes the bearer token and looks the hash up.
- **`refresh_expiry(settings)`** returns now + `JWT_REFRESH_TTL_DAYS` (default 7).
- **`witness_token_expiry(settings)`** returns now + `WITNESS_TOKEN_TTL_MIN` (default 240).
  The witness gets a link token that only opens their own session.

---

## `rbac.py`: role-based access control

The permission matrix is written once, as code, and covered cell by cell in
`tests/unit/test_rbac.py`:

| Action | Witness | Officer | Artist | Supervisor | Admin |
| --- | --- | --- | --- | --- | --- |
| create case / add witness / start session | no | own station | no | no | no |
| view case | own session | assigned | assigned | jurisdiction | no |
| edit sketch or scene | own session | assigned | assigned | no | no |
| view master (photoreal) image | no | assigned | assigned | jurisdiction | no |
| export | no | assigned | no | jurisdiction | no |
| view audit log | no | own cases | no | jurisdiction | no |
| verify audit chain | no | no | no | yes | yes |
| manage users | no | no | no | no | yes |

- **`Action`** (a `StrEnum`) lists the actions above.
- **`Scope`** (a dataclass) holds facts about the *target* case or session: `case_id`,
  `station`, `jurisdiction`, `assigned_user_ids`, `created_by`, `session_id`.
  **`Scope.is_assigned(user_id)`** is true when the user is assigned to the case or created it.
- **`WITNESS_ALLOWED`**: the only actions a witness token can ever perform are view and edit.
- **`can(principal, action, scope)`** returns `True`/`False` by walking the matrix:
  - A `system` principal can do anything.
  - A witness can act only on the session their token is bound to.
  - An officer creates within their own station and works on cases they are assigned to.
  - An artist views, edits and sees the master image on assigned cases.
  - A supervisor reads and exports within their jurisdiction and can verify the audit chain.
  - An admin manages users and verifies the audit chain, and nothing else.
- **`require(principal, action, scope)`** calls `can` and raises `Forbidden("Not allowed: <action>")`.

**How it's done:** services load the case or session, build a `Scope`, and call `require(...)`
before touching data. The check lives in the service layer, so it applies whether the call
comes from REST, a WebSocket or a background job.

---

## `crypto.py`: encrypted file storage

Uploaded and generated files (audio, sketches, portraits, exports) are encrypted at rest by
`app/services/storage.py` using these functions.

- **`derive_file_key(master_key, file_id)`** derives a separate 32-byte key per file with
  **HKDF-SHA256** (salt `nishaan-file-store-v1`, info = the file id) from the master key
  `FILE_MASTER_KEY_B64`. If one file key leaks, no other file is exposed.
- **`encrypt_bytes(master_key, file_id, plaintext)`** encrypts with **AES-256-GCM** using a
  random 12-byte nonce. The file id is also passed as *associated data*, so a blob copied onto
  another file id fails to decrypt. On-disk layout: `nonce (12 bytes) || ciphertext + 16-byte tag`.
- **`decrypt_bytes(master_key, file_id, blob)`** reverses this. It raises **`DecryptionError`**
  if the blob is too short or the GCM tag check fails (tampered data or wrong key).
- **`sha256_hex(data)`** returns a content hash, recorded for integrity and exports.

In production the app refuses to start without `JWT_SECRET` and `FILE_MASTER_KEY_B64`. In
development it uses throwaway keys and logs a warning (`app/main.py`).

---

## `audit.py`: the tamper-evident, hash-chained audit log

Every meaningful action (login, case created, statement recorded, sketch or scene version,
export...) writes an audit row. The rows form a **hash chain**:

```
hash = sha256(prev_hash + canonical_json(entry_without_hashes))
```

The first `prev_hash` is 64 zeros (`GENESIS_HASH`). Editing, deleting or reordering any past
row breaks every hash after it, and `verify_chain` reports the first broken row.

### Functions

- **`canonical_json(obj)`** gives stable JSON (sorted keys, compact separators, UTF-8), so the
  same entry always hashes the same way.
- **`compute_hash(prev_hash, entry)`** computes the SHA-256 chain step above.
- **`entry_dict_from_row(row)`** rebuilds the hashed fields from a stored `AuditLog` row
  (`at`, actor, session/case, action, object, ip, user agent, request id, details). The
  database's integer `id` is left out because it is assigned on insert.
- **`PendingEntry`** (dataclass) is an entry waiting to be written. **`to_dict(at)`** turns it
  into the hashed form, with timestamps as ISO-8601 UTC with microseconds.
- **`record(db, actor, action, *, object_type, object_id, session_id, case_id, details)`**
  **queues** an entry on the SQLAlchemy session (`db.info["audit_pending"]`). It does not
  write anything yet. Actor fields come from the `Principal`, and the user agent is cut to
  300 characters.
- **`pending_count(db)`** returns how many entries are queued. Used by tests.
- **`_chain_head(db)`** returns the newest row's hash, or the genesis hash.
- **`commit_with_audit(db)`** commits the business change **and** its audit rows in **one
  transaction**:
  1. With nothing queued, it is a plain `commit_tx`.
  2. Otherwise it takes a module-wide `asyncio.Lock`, so two requests can never chain onto
     the same head.
  3. On SQLite it opens the write transaction with `BEGIN IMMEDIATE`.
  4. It flushes the business change, reads the chain head, and chains and inserts each
     queued entry.
  5. It commits. On any error it rolls back the business change and the audit rows together,
     then clears the queue.

  It returns the number of entries written.
- **`VerifyResult`** (dataclass) holds `ok`, `checked`, `first_broken_id` and `reason`, with
  `as_dict()`.
- **`verify_chain(db)`** walks every row in id order, recomputes each `prev_hash` and `hash`,
  and returns the first mismatch. Exposed to supervisors and admins through
  `services/audit_service.py`.

**How it's done:** "queue during the request, write at commit" means an action is never saved
without its audit row, and an audit row never describes a change that was rolled back.

---

## `events.py`: in-process event bus for live updates

Pushes live updates (a transcript arrives, a sketch version is ready, job progress...) to the
witness and staff screens over the per-session WebSocket (`app/api/ws.py`).

- **`EVENT_TYPES`** lists the event names: `statement.transcribed`, `feature_sheet.updated`,
  `question.next`, `job.progress`, `version.created`, `stability.result`, `preview.ready`,
  `scene.updated`, `export.ready`, `error`.
- **`EventBus(max_queue=500)`** keeps a set of `asyncio.Queue`s for each session id.
  - **`subscribe(session_id)`** returns a new queue. Each open WebSocket gets its own.
  - **`unsubscribe(session_id, queue)`** removes it, and drops the session entry when it was
    the last one.
  - **`publish(session_id, event_type, payload)`** wraps the payload as
    `{"type", "session_id", "at", "data"}` and puts it on every subscriber's queue without
    waiting. If a slow client's queue is full, the **oldest event is dropped** instead of
    blocking the producer. The last 200 events per session are also kept in `history`, which
    tests use. A `None` session id is ignored.
  - **`subscriber_count(session_id)`** returns how many sockets are listening.

It runs in-process with no Redis or broker, which suits a single backend process.

---

## `jobs.py`: background job runner

Slow AI work (transcription, sketch generation, scene building, exports) runs as **jobs**. The
API answers `202 Accepted` with a `job_id` straight away, the work runs in the background, and
progress streams to the client over the event bus. Each job is a row in the `jobs` table plus
an `asyncio.Task`.

### `JobContext` (dataclass)

What a handler receives: `job_id`, `kind`, `session_id`, `payload`, `actor` (a `Principal`),
`db`, `bus` and `runner`.

- **`container`** gives the application container (providers, settings).
- **`await progress(pct, message)`** saves the progress percentage on the job row and
  publishes a `job.progress` event.

### `JobRunner`

- **`JobRunner(db, bus, inline=False)`** is created once by `app/container.py`.
  `inline=True` (`JOBS_INLINE=true`, used in tests) runs the job before `submit` returns.
- **`register(kind, handler)`** and the **`@runner.handler(kind)`** decorator map a job kind
  (e.g. `"scene.build"`) to an async function `handler(ctx, db_session) -> dict`.
- **`submit(kind, *, session_id, payload, actor)`**:
  1. Rejects unknown kinds with an `AppError` (`job_kind_unknown`).
  2. Inserts a `queued` job row and a `job.submitted` audit entry in one transaction.
  3. Starts the handler as an `asyncio.Task` (or runs it straight away when inline), keeping
     a reference so the task is not garbage-collected.
  4. Returns the job row.
- **`_run(ctx)`** is the task body:
  - It sets the request id for logs (the original request's id, or `job-<id>`).
  - It marks the job running (1 %) and runs the handler in its own database session.
  - On success it stores the result, sets `done` at 100 %, and publishes `job.progress` with
    the result.
  - On **`ProviderError`** it fails the job with `"<provider>: <message>"`.
  - On another **`AppError`** it fails the job with that error's message.
  - On **any other exception** it logs the stack trace and fails the job with only
    `internal error: <ExceptionType>`, so no internals leak.
  - Every failure publishes `job.progress` (status `failed`) and an `error` event.
- **`_set_progress`** and **`_finish`** update the job row (progress is clamped to 0–100).
- **`_publish_error`** sends the two failure events.
- **`wait_all(timeout)`** waits for running jobs. Used by tests.
- **`shutdown()`** cancels and waits for all tasks when the app stops (FastAPI lifespan in
  `app/main.py`).

Clients follow a job either over the WebSocket or by polling `GET /api/v1/jobs/{id}`.

---

## How the pieces fit at startup

`app/main.py → create_app()`:

1. `setup_logging(settings.log_level)`.
2. In production, refuses to start without `JWT_SECRET` and `FILE_MASTER_KEY_B64`.
3. Adds `RequestContextMiddleware` and CORS, then calls `install_error_handlers(app)` and
   `install_rate_limiting(app)`.
4. The lifespan builds the `Container`, which creates the `Database`, the `EventBus` and the
   `JobRunner` (and job handlers register on it). On shutdown, `container.stop()` calls
   `JobRunner.shutdown()`.

## Tests that cover this folder

- `tests/unit/test_rbac.py`: every cell of the permission matrix.
- `tests/unit/test_audit.py`: canonical JSON, the hash formula, the chain rolling back with
  the business change, database triggers that block UPDATE/DELETE on audit rows, tamper
  detection naming the exact row, and timestamp format.
- `tests/unit/test_crypto.py`: round-trip with distinct per-file keys, tampered ciphertext,
  wrong key or swapped file id, and the encrypted file store end to end.
- `tests/integration/test_flow.py`: error shape, tokens, jobs and WebSocket events end to end.
