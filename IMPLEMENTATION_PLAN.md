# Backend Implementation Plan — GPS Vehicle Tracking (FastAPI)

> Derived from `DESIGN_DECISIONS.md` (19 decisions, all confirmed 2026-09-05).
> **Frontend (Flutter) is explicitly deferred** until the backend is complete and verified.

---

## 1. Target architecture

```
backend/
├── app/
│   ├── main.py                    # app factory + lifespan (starts MQTT subscriber task)
│   ├── core/
│   │   ├── config.py              # pydantic-settings (env-driven, .env support)
│   │   ├── security.py            # argon2 hashing, JWT create/verify  [swap-point for Firebase]
│   │   ├── deps.py                # get_db, get_current_user, require_admin
│   │   └── exceptions.py          # AppError hierarchy + global handlers (error envelope)
│   ├── db/
│   │   ├── base.py                # Declarative base
│   │   ├── session.py             # async engine + session factory
│   │   └── seed.py                # python -m app.seed (demo users/routes/vehicles)
│   ├── models/                    # SQLAlchemy 2.0 (Mapped[...] style)
│   │   ├── user.py                # User: email, hashed_password, is_admin, route_id?, vehicle_id?
│   │   ├── route.py               # BusRoute: name, waypoints JSONB [{lat,lng}...]
│   │   ├── vehicle.py             # Vehicle: code (BUS-001), name, is_active
│   │   ├── gps_point.py           # GPSPoint: append-only history
│   │   └── current_location.py    # VehicleCurrentLocation: 1:1 upsert target
│   ├── schemas/                   # Pydantic v2: auth, user, route, vehicle, gps, common
│   ├── api/
│   │   ├── router.py              # aggregates v1 under /api/v1
│   │   └── v1/
│   │       ├── auth.py            # login, refresh
│   │       ├── me.py              # me, me/route, me/vehicle, location, history
│   │       └── admin/             # routes, vehicles, users, assignment
│   ├── services/                  # business logic (routers stay thin)
│   │   ├── auth_service.py        # verify creds, issue/refresh tokens
│   │   ├── assignment_service.py  # get-or-403 no_assignment logic
│   │   ├── tracking_service.py    # current location + derived status + history query
│   │   └── fleet_admin_service.py # admin CRUD + reassignment
│   └── mqtt/
│       ├── client.py              # aiomqtt subscriber, lifespan asyncio task
│       ├── payload.py             # strict GPS payload validation
│       └── handler.py             # validate → insert gps_points → upsert current_location
├── simulator/                     # python -m simulator (bonus)
│   ├── __main__.py
│   ├── config.py                  # interval, broker host/port
│   └── vehicle_sim.py             # waypoint interpolation + publish loop
├── alembic/                       # migrations
├── tests/
│   ├── conftest.py                # async client, test DB (real Postgres), factories
│   ├── test_auth.py               # login/refresh, bad creds, admin flag
│   ├── test_me_endpoints.py       # incl. cross-user authorization tests (graded evidence)
│   ├── test_admin.py              # CRUD + assignment, non-admin → 403
│   └── test_mqtt_handler.py       # valid/invalid payloads, upsert behavior (no broker)
├── deploy/
│   └── mosquitto.conf             # broker config (listener, allow_anonymous false later)
├── docker-compose.yml             # api, db, mosquitto (+ profiles: sim)
├── Dockerfile                     # python:3.12-slim, uvicorn
├── pyproject.toml                 # deps + ruff + pytest config
├── .env.example
└── README.md                      # submission README (written last)
```

## 2. Data model (v1)

| Table | Key columns | Notes |
|---|---|---|
| `users` | id PK, email (unique), hashed_password, is_admin (bool), route_id FK nullable, vehicle_id FK nullable | Assignment = nullable FKs on user; NULL ⇒ `no_assignment` error |
| `bus_routes` | id PK, name (unique), waypoints JSONB `[{lat, lng}...]` (ordered) | JSONB per decision #6 |
| `vehicles` | id PK, code (unique, e.g. BUS-001), name, is_active | |
| `gps_points` | id PK, vehicle_id FK, lat `Numeric(9,6)`, lng, speed (km/h), recorded_at `timestamptz` | Append-only; index `(vehicle_id, recorded_at DESC)` |
| `vehicle_current_location` | vehicle_id PK+FK (1:1), lat, lng, speed, recorded_at, updated_at | Upserted by MQTT handler |

**Micro-decisions made during planning** (not grilled, flagged for review):
- Integer PKs (bigserial) — simple URLs/debugging; `/me/*` design already prevents ID enumeration.
- Coordinates `Numeric(9,6)` — ~0.11 m precision, standard for GPS.
- Staleness window 60 s (configurable `GPS_STALENESS_SECONDS`), moving threshold 5 km/h (`MOVING_SPEED_KMH`).
- JWTs via PyJWT; refresh tokens stored stateless (expiry-only) — no revocation table at assessment scale.
- MQTT QoS 1 (at-least-once); anonymous broker locally, `allow_anonymous false` + password file documented in README.

## 3. Build order

| Phase | Deliverable | Acceptance criteria |
|---|---|---|
| **0. Scaffold** | `backend/` skeleton, `pyproject.toml` (fastapi, uvicorn[standard], sqlalchemy[asyncio], asyncpg, alembic, pydantic-settings, pwdlib[argon2], pyjwt, aiomqtt; dev: pytest, pytest-asyncio, httpx, ruff), `.env.example`, ruff clean | `uvicorn app.main:app` boots with `/health` returning 200 |
| **1. Models + migration** | All 5 models, Alembic initial migration | `alembic upgrade head` creates schema; FKs + index present |
| **2. Core layer** | config, security, exceptions (error envelope), deps | unit tests: hash/verify round-trip; JWT create/verify; envelope shape |
| **3. Auth API** | `POST /auth/login`, `POST /auth/refresh` | tests: valid creds → tokens; wrong password → 401 `invalid_credentials`; expired access → refresh works |
| **4. Admin API** | routes/vehicles/users CRUD + `PUT /admin/users/{id}/assignment` | tests: admin CRUD OK; non-admin → 403 `forbidden`; duplicate email → 409 |
| **5. /me API** | `me`, `me/route`, `me/vehicle`, `me/vehicle/location`, `me/vehicle/history` | tests: assigned user sees own data; **unassigned → 403 `no_assignment`; User A cannot read User B (403/404)** |
| **6. MQTT ingestion** | aiomqtt subscriber (lifespan), payload validation, handler (insert history + upsert current) | unit tests: valid payload persists both tables; malformed payload logged + discarded, no crash |
| **7. Seed** | `python -m app.seed` → 2+ users (1 admin), 2 routes w/ waypoints, 2 vehicles, assignments | re-run idempotent; User A↔Route A/BUS-001, User B↔Route B/BUS-002 |
| **8. Test suite green** | full pytest run vs real Postgres test DB | `pytest` exits 0; authorization tests present and passing |
| **9. Docker** | Dockerfile + docker-compose (api, db, mosquitto; `--profile sim` for simulator) | `docker compose up` → healthy stack; `docker compose run --rm api python -m app.seed` seeds |
| **10. Simulator** | `simulator/` package | `python -m simulator` publishes ~0.5 msg/s/vehicle; vehicles move along waypoints; status flips moving/idle/offline correctly |
| **11. README** | Submission README: setup, architecture diagram, DB design, endpoint table, auth flow, assignment logic, GPS flow, compose instructions | matches PDF submission checklist |

## 4. End-to-end verification (definition of done)

1. `docker compose up -d` → api + db + mosquitto healthy
2. `docker compose run --rm api python -m app.seed`
3. `docker compose --profile sim up -d simulator` → GPS flowing
4. Login as **User A** → `GET /me/route` returns **Route A only**, `/me/vehicle/location` returns BUS-001 moving along the polyline
5. Login as **User B** → sees only Route B/BUS-002; calling anything of User A's is impossible by API design (`/me/*` scoping) and covered by tests
6. Stop simulator 60 s → status becomes `offline`
7. `pytest` green; README complete

## 5. Explicitly out of scope (recorded, not silently assumed)

- Public signup / registration (users created via seed/admin only — decision #10)
- Firebase integration (swap-ready abstraction only — decision #10)
- REST GPS ingestion adapter (MQTT-only — decision #9)
- Token revocation table, rate limiting, horizontal scaling (noted as future work in README)
- Frontend/Flutter work (next major milestone, after backend DoD)
