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

Upstream images: `ghcr.io/eigger/garage-api:0.2.14`, `garage-web:0.2.14`
