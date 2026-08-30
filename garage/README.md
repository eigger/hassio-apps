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
a PR whenever upstream — or the add-on base image — publishes a newer tag.

## Options

None. Garage manages its integration keys itself — Opinet, 천안사랑카드, the EV
charger API and Web Push (VAPID, generated with a button) all live in the app's
**/integrations** screen. The API resolves them through `getSetting()`, which
prefers the value in its own database and only falls back to the environment, so
an add-on option would be ignored as soon as anything is saved in the UI.

## Architecture

`amd64` only — upstream publishes no arm64 image, so the app cannot be built for
Raspberry Pi or other aarch64 hosts.
