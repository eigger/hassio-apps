# Garage (Home Assistant App)

Runs [garage](https://github.com/eigger/garage) **all-in-one** (Postgres + API + Web), with nginx routing like the upstream Caddyfile.

## Install

1. **Settings → Apps → ⋮ → Repositories** → add this repo
2. Install **Garage**, start it
3. Open **http://&lt;home-assistant-ip&gt;:3081** (or use **Open Web UI**)

First launch: create an admin on `/login`.

API keys are configured in the Garage web UI. JWT/DB secrets are auto-generated under `/data`.

## Why not Ingress?

Garage’s Next.js UI uses absolute `/_next` and `/api` paths. HA Ingress serves under a subpath, so you get a blank/broken page. Host-port access matches the original docker-compose setup (same origin).

Default host port is **3081** so it does not collide with Stash (**3080**).

Upstream images: `ghcr.io/eigger/garage-api:1.3.6`, `ghcr.io/eigger/garage-web:1.3.6`

Nothing is built from source here — the app copies the upstream release images in and
runs them next to Postgres and nginx, so the app version tracks the upstream version.
A scheduled workflow ([upstream-bump.yml](../.github/workflows/upstream-bump.yml)) opens
a PR whenever upstream publishes a newer tag.

## Options

All optional, all blank by default — the app runs without any of them.

| Option | Upstream env | What it does |
|---|---|---|
| `opinet_api_key` | `OPINET_API_KEY` | Real nearby fuel prices; falls back to mock data when unset |
| `cheonan_card_enabled` | `CHEONAN_CARD_ENABLED` | 천안사랑카드 stations — needs the Opinet key too |
| `ev_charger_api_key` | `EV_CHARGER_API_KEY` | 한국환경공단 EV charger data (data.go.kr); mock data when unset |
| `vapid_public_key` / `vapid_private_key` / `vapid_subject` | `VAPID_*` | Web Push reminders (`npx web-push generate-vapid-keys`) |

## Architecture

`amd64` only — upstream publishes no arm64 image, so the app cannot be built for
Raspberry Pi or other aarch64 hosts.
