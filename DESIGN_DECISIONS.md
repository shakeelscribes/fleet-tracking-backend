# Design Decision Record — GPS Vehicle Tracking System

> **Project:** Full Stack Developer Assessment — FastAPI + Flutter GPS Vehicle Tracking
> **Source:** `Assessment Task Full Stack Flutter Python Tracking -3.pdf`
> **Scope of this record:** Backend design only. Frontend decisions will be appended later, after the backend is complete.
> **Status:** Grilling complete — Round 1 + auth revisit + Round 2, all confirmed 2026-09-05. Next: `IMPLEMENTATION_PLAN.md`.

---

## 1. Database Engine

- **Decision:** PostgreSQL 16 + SQLAlchemy 2.0 (async) + Alembic migrations
- **Reason:** The task allows MySQL or PostgreSQL. PostgreSQL was chosen for JSONB support (used for route waypoint geometry), richer indexing options, and it is the most common production pairing with FastAPI. SQLAlchemy 2.0 async style is the modern FastAPI idiom; Alembic gives versioned, reviewable schema migrations.

## 2. Project Layout & Layering

- **Decision:** Layered modular single-repo layout
  (`app/api/`, `app/services/`, `app/core/`, `app/models/`, `app/schemas/`, `app/mqtt/`, `app/db/`)
- **Reason:** "Clean, modular, production-ready architecture" is a graded requirement. The layered layout (api → services → db) demonstrates production structure with clear seams, while staying right-sized for an assessment. The domain-first modular monolith alternative was considered but judged to be over-engineering for this scope.

## 3. Authentication

- **Decision:** JWT access token (~30 min) + refresh token (~7 days) with `/auth/refresh` endpoint; password hashing via `pwdlib[argon2]`
- **Reason:** Refresh-token flow is production-realistic and the Flutter app will need it for long-lived sessions. `pwdlib` with argon2 was chosen over the aging `passlib`/bcrypt stack as the currently maintained modern option.

## 4. MQTT Broker

- **Decision:** Eclipse Mosquitto, running in Docker Compose alongside the API and PostgreSQL
- **Reason:** Task prefers MQTT ingestion; Mosquitto is a tiny (~5 MB) image with trivial configuration, ideal for a local Docker Compose stack. EMQX (heavier) and HiveMQ Cloud (external dependency) were considered and passed over.

## 5. MQTT Subscriber Process Model

- **Decision:** In-process asyncio task started from FastAPI's lifespan hook, implemented as a self-contained `app/mqtt/` module
- **Reason:** Single container keeps the Docker Compose file and test story simple. The subscriber is written as a self-contained module so it can later be lifted into a standalone worker container without redesign.

## 6. Route Geometry

- **Decision:** Routes carry an ordered waypoint list (polyline) stored as JSONB, served through the assigned-route API
- **Reason:** The Flutter app must visualize the bus route on a map, so a route is more than a name. JSONB array of `{lat, lng}` objects leverages the PostgreSQL choice; a strict relational child-table alternative was considered but rejected as unnecessary for the scale.

## 7. Assignment Management & Admin Capability

- **Decision:** Seed script **plus** minimal admin API; `is_admin` flag on users; admin-only endpoints for CRUD of routes/vehicles and reassignment of users
- **Reason:** The core rule (one route + one vehicle per user, enforced by backend) is graded. Admin endpoints demonstrate that role-based authorization is real rather than only "user sees own row", at low implementation cost.

## 8. Latest-Location Strategy

- **Decision:** Denormalized 1:1 `vehicle_current_location` table, upserted on every MQTT message; `gps_points` remains append-only history with an index on `(vehicle_id, timestamp DESC)`
- **Reason:** The task requires both latest location and historical data. A dedicated current-location table gives fast reads for the Flutter home screen and keeps history clean; query-time derivation (option A) was rejected for slower reads, and columns-on-vehicles (option C) for polluting the vehicle entity.

## 9. REST Fallback Ingestion

- **Decision:** MQTT-only ingestion for this assessment
- **Reason:** The task explicitly prefers MQTT, the GPS simulator publishes over MQTT, and skipping a REST ingestion path keeps scope tight. The README will note that the `app/mqtt/` design allows a REST ingestion adapter later.

---

## Round 2 + Auth Revisit — confirmed 2026-09-05 ("go with the recommended things")

### 10. Authentication architecture (revisited — user raised Firebase)

- **Decision:** Backend-issued JWT (access ~30 min + refresh ~7 days) is the **only** auth path in the demo. Auth logic (hashing, token create/verify, current-user resolution) lives behind a provider-style module (`app/core/security.py` + deps) so **Firebase can be swapped in later without touching routers**. No public signup in the demo — users are created by seed script + admin endpoint.
- **Reason:** The task requires "multiple user logins", not self-registration. Keeps the Docker Compose demo fully offline-runnable and keeps graded auth logic inside the backend. User's motive ("easy to grow into something in the future") is satisfied by the swap-ready abstraction.
- **Rejected:** Firebase-only auth (would require a Firebase project + internet for the demo and move graded auth to a third party).

### 11. Unassigned-user behavior

- **Decision:** `/me/route`, `/me/vehicle`, `/me/vehicle/location`, `/me/vehicle/history` return `403 {"error": {"code": "no_assignment", ...}}` when the user has no route/vehicle assigned.
- **Reason:** Proves assignment is backend-enforced; explicit structured error beats silent empty data. Flutter will show "no route assigned — contact admin".

### 12. API surface & versioning

- **Decision:** `/api/v1` prefix; permissive CORS in dev (configurable). Endpoints:
  - **Auth:** `POST /api/v1/auth/login`, `POST /api/v1/auth/refresh`
  - **User (assignment-scoped):** `GET /api/v1/me`, `GET /api/v1/me/route`, `GET /api/v1/me/vehicle`, `GET /api/v1/me/vehicle/location`, `GET /api/v1/me/vehicle/history?from=&to=&limit=&offset=`
  - **Admin (is_admin):** CRUD `/api/v1/admin/routes`, `/api/v1/admin/vehicles`, `/api/v1/admin/users`, plus `PUT /api/v1/admin/users/{id}/assignment`
- **Reason:** `/me/*` scoping makes authorization structural — a user can only ever read their own vehicle, so ID-guessing attacks are impossible by design.

### 13. Error format

- **Decision:** Global exception handlers produce `{"error": {"code": "...", "message": "..."}}` on every error, including reshaped 422 validation errors.
- **Reason:** Stable machine-readable contract for Flutter; strong production-readiness signal.

### 14. History query semantics

- **Decision:** `from`/`to` ISO-8601 (default last 24h), `limit` (default 200, max 1000), `offset`, ordered `recorded_at DESC`.
- **Reason:** Time-range is the natural query shape for GPS series; offset pagination is adequate at assessment scale (cursor pagination noted as overkill).

### 15. Vehicle status semantics

- **Decision:** Derived at read time: `moving` (fresh point + speed > 5 km/h), `idle` (fresh point + speed ≤ 5), `offline` (no point within staleness window, default 60 s, configurable).
- **Reason:** Truthful by construction — status follows actual data flow; a manual status field would go stale.

### 16. GPS payload & validation

- **Decision:** Topic `fleet/{vehicle_id}/gps`; JSON payload `{vehicle_id, lat, lng, speed, timestamp}`; strict validation (lat ∈ [-90,90], lng ∈ [-180,180], speed ≥ 0, timestamp parseable) — invalid messages are **logged and discarded**, the subscriber never crashes; timestamps stored as `timestamptz` UTC (missing → server time); speed in km/h.
- **Reason:** Defensive ingestion — one malformed message must never take down the pipeline.

### 17. Testing strategy

- **Decision:** pytest + pytest-asyncio + httpx `AsyncClient` against a **real PostgreSQL** test DB; **dedicated cross-user authorization tests** (User A cannot read User B's route/vehicle — the graded rule as executable evidence); unit tests for the MQTT handler with a fake DB session (no broker needed).
- **Reason:** Authz tests double as submission evidence; handler unit tests validate ingestion cheaply.

### 18. Docker Compose scope

- **Decision:** Core services: `api`, `db` (postgres:16), `mosquitto`. Optional Compose **profiles**: `simulator` (`--profile sim`); one-shot seed via `docker compose run --rm api python -m app.seed`. No pgAdmin.
- **Reason:** Lean stack that satisfies the bonus requirement; optional pieces don't burden the core demo.

### 19. GPS simulator

- **Decision:** `simulator/` package **inside the backend repo** (submission is two repos, so it ships with the backend). Reads routes/vehicles from the DB, walks each vehicle along its route's waypoints with interpolation, publishes to `fleet/{vehicle_id}/gps` every ~2 s (configurable), asyncio-concurrent multi-vehicle. Runnable standalone (`python -m simulator`) or via compose profile.
- **Reason:** Bonus requirement; the sole dev data source; waypoint-walking makes the Flutter map view demo meaningful.

### 20. Demo data scale & city (richer seed)

- **Decision:** Seed **4 users + 1 admin, 4 routes, 4 vehicles** (strict 1:1:1 assignment pairs), all routes along **real Chennai corridors** with ~10–15 waypoints each:

  | User | Route | Vehicle |
  |---|---|---|
  | ravi@example.com | Route A — City Center ↔ Airport | BUS-001 |
  | priya@example.com | Route B — OMR Tech Corridor (Tidel Park ↔ Sholinganallur) | BUS-002 |
  | arun@example.com | Route C — Marina Beach ↔ Chennai Central | BUS-003 |
  | divya@example.com | Route D — T. Nagar ↔ Guindy | BUS-004 |
  | admin@fleet.com | *(admin, no assignment — admin API demo)* | — |

- **Reason:** Proves the design scales beyond the minimum while every PDF condition still holds ("one bus route and vehicle to each user" is the hard cap — richer means *more users*, never two routes for one user). Zero schema/API/simulator changes required. README keeps User A vs User B as the headline demo pair.
- **Rejected:** exactly-2 fixtures (rule demo works but looks sparse); multi-route-per-user (violates the PDF).

### 21. Deployment scope

- **Decision:** Assessment-only. No paid hosting, no live URL cost, no spend. The Docker Compose stack is the final runnable artifact — the grader runs it locally per the README.
- **Reason:** User's call: the assessment verifies ability via the two GitHub repos + READMEs; zero budget is available and none is needed.
- **⚠️ Amendment — STRICT USER INSTRUCTION (recorded on explicit command, 2026-09-05):**
  - The **Docker Compose stack (api + postgres + mosquitto) is confirmed as the PDF bonus deliverable** and remains in the repository permanently.
  - Any cloud-demo work (Render free hosting of the API, Flutter APK releases via GitHub Actions) is **additive only** — it must never remove or weaken the compose stack or the offline grading path.
  - Finalization of the cloud demo (future Phase 12) awaits the user's explicit broker-mode choice: **B — HiveMQ Cloud MQTT** (keeps MQTT end-to-end) or **C — REST ingest endpoint** (PDF-sanctioned fallback). Nothing else is recorded for the cloud demo until then.

### 22. Cloud demo delivery — broker mode B: HiveMQ Cloud (strict user instruction, 2026-09-05)

- **Decision:** The hosted demo runs entirely on free tiers (₹0):
  - **API:** Render free web service (Docker deploy of the same backend image) → `https://<app>.onrender.com`
  - **MQTT:** **HiveMQ Cloud free tier** as the hosted-environment broker — the API subscribes **outbound** (Render allows outbound TLS; only inbound is HTTP-restricted), simulator publishes to it. MQTT stays end-to-end, honoring the PDF's "MQTT is preferred".
  - **DB:** Render free Postgres (or Neon free) via `DATABASE_URL`; ~30-day free-tier expiry acknowledged — deploy near submission, seed is idempotent
  - **Simulator on cloud:** in-process inside the API behind `SIMULATOR_ENABLED=true` env flag (GitHub Actions cron as fallback)
  - **Flutter delivery:** GitHub Actions builds release APK (`flutter build apk --release --dart-define=API_BASE_URL=...`) → attached to the Flutter repo's **GitHub Releases**; endpoints baked in; optional runtime URL override on the login screen so the APK also works against a local compose instance
- **Reason:** MQTT is the PDF's preferred ingestion path — option C would abandon the preference. HiveMQ Cloud is the only free way to keep a real broker since Render free cannot host Mosquitto's TCP port. Grader experience: install APK → login with seeded creds → live Route A/BUS-001 without running anything locally.
- **Known free-tier caveats (accepted, documented in README):** Render cold start ~50 s after 15 min idle (our loading states handle it); free DB expiry ~30 days (re-seed in seconds).
- **Rejected:** C (REST ingest — PDF-sanctioned but drops the preferred path); any paid hosting.
