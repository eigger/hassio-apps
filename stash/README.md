# Stash (Home Assistant App)

Runs [stash](https://github.com/eigger/stash) **all-in-one** (Postgres + API + Web), with nginx routing like the upstream Caddyfile.

## Install

1. **Settings → Apps → ⋮ → Repositories** → add this repo
2. Install **Stash**, start it
3. Open **http://&lt;home-assistant-ip&gt;:3080** (or use **Open Web UI**)

First launch: create an admin on `/login`.

Integrations are configured in the Stash web UI. JWT/DB secrets are auto-generated under `/data`.

## Why not Ingress?

Stash’s Next.js UI uses absolute `/_next` and `/api` paths. HA Ingress serves under a subpath, so CSS/JS and API calls break. Host-port access matches the original docker-compose setup (same origin).

Upstream images: `ghcr.io/eigger/stash-api:0.3.1`, `stash-web:0.3.1`
