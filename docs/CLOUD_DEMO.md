# Cloud demo runbook (Phase 12)

Zero-budget deployment of the demo stack: **Render** (free web service + free Postgres)
and **HiveMQ Cloud** (free broker tier). Everything the grader needs locally still works
via `docker compose up` — this cloud path is the bonus on top (decision #18/#22).

```
Flutter app / curl / grader
        │ HTTPS + JWT
        ▼
Render web service (this repo's backend/Dockerfile)
   ├─ alembic upgrade head && python -m app.seed   (on boot)
   ├─ in-process MQTT subscriber ──┐
   ├─ in-process simulator (buses)─┤  TLS :8883
   ▼                               ▼
Render Postgres (free)        HiveMQ Cloud (free, serverless)
```

## 1. HiveMQ Cloud broker (~5 min)

1. Sign up at <https://www.hivemq.com/mqtt-cloud-broker/> (free "Serverless" tier).
2. Create a cluster → note the **URL** (e.g. `abc123.s1.eu.hivemq.cloud`).
3. Under *Access Management* create credentials (username + password) — the free tier
   requires authentication.
4. Allow connections on the default **TLS port 8883** (serverless always TLS).

You now have: host, port 8883, username, password → used in step 3.

## 2. Push the repo to GitHub

```bash
cd C:/vehicle-tracking-assessment
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

CI (`.github/workflows/backend-ci.yml`) will run ruff + the 196-test suite against a
real Postgres service container on every push.

## 3. Render deploy (~10 min)

**Option A — Blueprint (recommended):** Render Dashboard → *New* → *Blueprint* → pick the
repo. `render.yaml` at the repo root provisions the web service + free Postgres and wires
`DATABASE_URL` automatically. Fill in the three `sync: false` values when prompted:
`MQTT_HOST` (the HiveMQ URL), `MQTT_USERNAME`, `MQTT_PASSWORD`.

**Option B — Manual:** New → *Web Service* → point at the repo → runtime **Docker**
(dockerfilePath `backend/Dockerfile`) → add env vars:

| Key | Value |
|---|---|
| `DATABASE_URL` | *link the Render Postgres (Internal Database URL) — `postgresql://` is normalised to `postgresql+asyncpg://` automatically* |
| `JWT_SECRET_KEY` | long random string (Render "Generate") |
| `MQTT_ENABLED` | `true` |
| `MQTT_HOST` | `<your-cluster>.s1.eu.hivemq.cloud` |
| `MQTT_PORT` | `8883` |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | your HiveMQ credentials |
| `MQTT_TLS` | `true` |
| `SIMULATOR_ENABLED` | `true` |
| `SEED_PASSWORD` | `password123` |
| `LOG_LEVEL` | `INFO` |

On boot, the container migrates, seeds, starts the MQTT subscriber (TLS) and the
in-process simulator — the four Chennai buses start driving immediately.

## 4. Verify

```bash
BASE=https://<your-service>.onrender.com

curl -s $BASE/health
TOKEN=$(curl -s -X POST $BASE/api/v1/auth/login -H "Content-Type: application/json" \
  -d '{"email":"ravi@fleet.com","password":"password123"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s $BASE/api/v1/me/vehicle/current -H "Authorization: Bearer $TOKEN"
# repeat after a few seconds: lat/lng should advance along the route

# publish your own fix through HiveMQ (from anywhere):
#   mosquitto_pub -h <cluster>.s1.eu.hivemq.cloud -p 8883 -u <user> -P <pass> \
#     --capath /etc/ssl/certs -t fleet/1/gps \
#     -m '{"vehicle_id":1,"lat":13.0827,"lng":80.2707,"speed":40,"timestamp":"<now>Z"}'
```

Also check the Render logs once: expect `MQTT connected to ...:8883` (TLS), the seed
summary, and `Simulator publishing for 4 vehicle(s)`.

## 5. Flutter release channel (ready for the app phase)

`.github/workflows/release-apk.yml` triggers on `v*` tags (or manually). Until the
Flutter app exists it exits gracefully with a skip message; once `flutter/` is in the
repo, tagging `v0.1.0` builds `app-release.apk` and attaches it to a GitHub Release —
which is how the grader installs the app without building it.

## Free-tier caveats (expected behaviour, not bugs)

- **Cold starts:** a free Render service sleeps after ~15 min idle; the first request
  afterwards takes ~50–60 s. Hit `/health` twice before demoing.
- **Free Postgres expires** after 30 days; recreate it (data is disposable seed data) or
  point `DATABASE_URL` at another free provider (e.g. Neon).
- **Render egress IPs** are dynamic — HiveMQ serverless allows any client with valid
  credentials, so nothing to whitelist.
- The simulator writes continuously; the free Postgres (1 GB) is far larger than a demo
  ever needs, but `docker compose down -v`/redeploy resets everything anyway.
