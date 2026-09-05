# Fleet Tracking — FastAPI Backend

A GPS vehicle-tracking backend for the Full Stack Developer assessment: drivers are assigned
1:1 to a vehicle and a route, GPS fixes arrive over **MQTT**, and every consumer reads live
positions, route polylines, and history through a **JWT-secured REST API**.

```
                             ┌────────────────────────┐
  GPS devices / simulator    │  FastAPI (uvicorn)     │   Flutter app / curl
  ────mosquitto_pub────┐     │  ┌──────────────────┐  │   ────HTTPS / JWT────┐
                       │     │  │ REST API         │◄─┼──────────────────────┘
                       ▼     │  │ + in-process     │  │
               ┌──────────┐  │  │   MQTT subscriber│  │
               │ Mosquitto│──┴──►└────────┬─────────┘  │
               │  broker  │   validate →  │ async SQLAlchemy
               └──────────┘   discard bad │ ▼
                              data quietly│ ┌────────────┐
                                          │ │ PostgreSQL │
                                          │ └────────────┘
```

- **Ingestion:** topic `fleet/<vehicle_id>/gps`, QoS 1, JSON payload (contract below).
  Invalid or mismatched messages are logged and discarded — the pipeline never crashes.
- **Latest fix per vehicle** lives in `vehicle_current_location` (1:1, upserted); full
  trail in `gps_points` (JSONB route waypoints on `bus_routes`).
- **Status is derived:** `offline` if the last fix is > 60 s old, else `moving` if
  speed > 5 km/h, else `idle`.
- **Security:** argon2 password hashes, JWT access (30 min) + refresh (7 d) tokens,
  admin-only `/api/v1/admin/*` (role gate), strict row ownership on `/api/v1/me/*`
  (a driver can only ever read their own assignment/route/vehicle/history).
- **Errors are uniform:** every deliberate failure is
  `{"error": {"code": "<machine-readable>", "message": "<human>"}}`, including 422s
  (reshaped to `code: "validation_error"`).

## Quickstart (Docker — the one command)

```bash
docker compose up --build
```

That boots **Postgres + Mosquitto + API**, then the API container runs
`alembic upgrade head && python -m app.seed` before serving. No other steps needed.

- Swagger UI: http://localhost:8000/docs
- Health: http://localhost:8000/health
- Host ports: API **8000**, broker **1883**, Postgres **5433** (deliberately not 5432 so a
  local dev Postgres can run alongside)

Optional — make the fleet drive itself (walks the seeded buses along their routes,
publishing fixes every 2 s):

```bash
docker compose --profile sim up -d
```

### 90-second demo

```bash
# 1) login as a driver (seeded accounts all use password123)
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"ravi@fleet.com","password":"password123"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2) his assignment (route + vehicle)
curl -s http://localhost:8000/api/v1/me/assignment -H "Authorization: Bearer $TOKEN"

# 3) push a GPS fix through the broker, as a real device would
docker compose exec mosquitto mosquitto_pub -t fleet/1/gps -m \
  '{"vehicle_id":1,"lat":13.0827,"lng":80.2707,"speed":42.5,"timestamp":"2026-09-05T18:30:00Z"}'

# 4) the bus is now "moving" at that spot
curl -s http://localhost:8000/api/v1/me/vehicle/current -H "Authorization: Bearer $TOKEN"

# 5) history window (defaults to last 24h)
curl -s "http://localhost:8000/api/v1/me/vehicle/history?from=2026-09-05T00:00:00Z&to=2026-09-06T00:00:00Z" \
  -H "Authorization: Bearer $TOKEN"
```

Robustness check — the pipeline eats garbage without flinching:

```bash
docker compose exec mosquitto mosquitto_pub -t fleet/1/gps -m 'not json at all'
docker compose exec mosquitto mosquitto_pub -t fleet/1/gps -m \
  '{"vehicle_id":1,"lat":999,"lng":80.27,"speed":1,"timestamp":"2026-09-05T18:30:00Z"}'
# -> api logs show discard warnings, zero tracebacks, /health stays 200
```

## Seeded demo data (Chennai)

Created idempotently on every API boot (`python -m app.seed`; `--fresh` wipes and rebuilds).
All accounts use password `password123`.

| User | Role | Vehicle | Route |
|---|---|---|---|
| admin@fleet.com | admin | — (manages everything) | — |
| ravi@fleet.com | driver | BUS-001 Chennai Express | City Center to Airport |
| priya@fleet.com | driver | BUS-002 OMR Flier | OMR Tech Corridor |
| arun@fleet.com | driver | BUS-003 Marina Cruiser | Marina to Central |
| divya@fleet.com | driver | BUS-004 Guindy Shuttle | T. Nagar to Guindy |

Assignments are exclusive: one route ↔ one vehicle ↔ one driver. The admin API enforces it
with `409` codes like `route_already_assigned` / `vehicle_in_use` / `route_name_taken`.

## Running without Docker (dev)

Python 3.11 and a Postgres (e.g. `docker run -e POSTGRES_PASSWORD=tracking -p 5432:5432 postgres:16-alpine`):

```bash
py -3.11 -m venv .venv
.venv/Scripts/pip.exe install -e ".[dev]"        # Linux/macOS: .venv/bin/pip
cp .env.example .env                              # adjust DATABASE_URL if needed
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m app.seed              # idempotent demo data
.venv/Scripts/python.exe run.py                   # http://localhost:8000/docs
```

`run.py` starts uvicorn with a **selector** event loop (required for MQTT on Windows
Proactor defaults) and honours `LOG_LEVEL` / `HOST` / `PORT` env vars.

## Tests & coverage

Integration tests run against a **real PostgreSQL** database (`tracking_test` on the same
server — no SQLite mocks; tests drop/recreate the schema per test for full isolation).

```bash
# needs a Postgres reachable at localhost:5432 (user/pass tracking:tracking)
.venv/Scripts/python.exe -m pytest -q             # 200 tests
.venv/Scripts/python.exe -m pytest -q --cov=app   # coverage report
.venv/Scripts/ruff.exe check app tests            # lint (clean)
# or, with make:  make test / make coverage / make lint
```

Current numbers: **200 passed · 96% line coverage** (all services and schemas at 100%;
the uncovered remainder is the broker-connection loop verified by live E2E tests and a
production-only launcher shim).

> Note: the test suite uses port **5432** while the compose demo publishes Postgres on
> **5433** — both can run simultaneously. If pytest errors on *every* test with connection
> errors, your Postgres on 5432 is simply not running.

## API surface (v1, JWT bearer)

| Method & path | Who | Purpose |
|---|---|---|
| `POST /api/v1/auth/login` | public | email+password → access + refresh token |
| `POST /api/v1/auth/refresh` | public | refresh token → new pair |
| `GET /api/v1/me/assignment` | driver | own route + vehicle |
| `GET /api/v1/me/route` | driver | own route polyline (JSONB waypoints) |
| `GET /api/v1/me/vehicle/current` | driver | live position + derived status |
| `GET /api/v1/me/vehicle/history` | driver | fixes in a time window |
| `POST/GET/PATCH/DELETE /api/v1/admin/routes[...]` | admin | route CRUD (delete blocked while assigned) |
| `POST/GET/PATCH/DELETE /api/v1/admin/vehicles[...]` | admin | vehicle CRUD (delete blocked while assigned) |
| `POST/GET/PATCH/DELETE /api/v1/admin/users[...]` | admin | user CRUD + role/assignment handling |
| `PUT /api/v1/admin/users/{id}/assignment` | admin | set/clear the exclusive route+vehicle pair |

## MQTT ingestion contract

- **Topic:** `fleet/<vehicle_id>/gps` — payload `vehicle_id` must match the topic id.
- **Payload:** `{"vehicle_id": 1, "lat": 13.0827, "lng": 80.2707, "speed": 42.5,
  "timestamp": "2026-09-05T18:30:00Z"}` — lat ±90, lng ±180, speed 0–300,
  tz-aware ISO timestamp.
- **Behaviour:** unknown/inactive vehicle, schema violation, or topic/payload mismatch →
  warning log + discard. Valid fix → insert into `gps_points` + upsert
  `vehicle_current_location` (latest fix wins).
- The subscriber runs **inside the API process** (lifespan-gated by `MQTT_ENABLED`),
  reconnects every 5 s, subscribes with QoS 1.

## Layout

```
app/
├── api/v1/        # auth, me, admin (routes/vehicles/users)
├── core/          # config, security (JWT/argon2), deps, exceptions, loops
├── db/            # async engine/session, DeclarativeBase
├── models/        # User, BusRoute, Vehicle, GPSPoint, VehicleCurrentLocation
├── schemas/       # pydantic request/response models
├── services/      # business logic (auth, fleet admin, tracking)
├── mqtt/          # payload validation, message handler, broker client
├── seed.py        # idempotent demo data (python -m app.seed)
└── main.py        # app assembly + lifespan (MQTT subscriber)

simulator/          # GPS bus simulator (python -m simulator, compose "sim" profile)
tests/              # 200 integration tests against real PostgreSQL
alembic/            # migrations; Dockerfile + docker-compose.yml at the repo root
```

> **Submission layout (per the assessment):** this repository is the *backend*.
> The Flutter client lives in its own companion repository
> (`<same-name>-frontend`), with its own README and an APK-release workflow.

Design decisions and their rationale live in [`DESIGN_DECISIONS.md`](DESIGN_DECISIONS.md);
the build order in [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).
