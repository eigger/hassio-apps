# Stash (Home Assistant App)

Runs [stash](https://github.com/eigger/stash) (home inventory & barcode manager) **all-in-one inside one app**, similar to an LXC:

- PostgreSQL 16
- Stash API (`ghcr.io/eigger/stash-api:0.3.1`)
- Stash Web (`ghcr.io/eigger/stash-web:0.3.1`)
- Nginx (Ingress `:8099`, routes `/api`, `/health`, and the UI)

## Install

1. HA → **Settings → Apps → ⋮ → Repositories**
2. Add this repository URL
3. Install **Stash** and start it
4. Open **Stash** from the sidebar (Ingress)

On first launch, create an admin account via **Create first admin** on `/login`.

Integrations (webhook, barcode lookup, public URL, push, …) are configured in the Stash web UI.  
`JWT_SECRET` and Postgres credentials are auto-generated and stored under `/data`.

## Ingress notes

Ingress is proxied under a Supervisor subpath. Absolute root paths (e.g. `/api`) in the web app can break under Ingress. If that happens, map host port `3080/tcp` for direct access, or adapt the app to relative paths / `basePath`.

Upstream: [eigger/stash](https://github.com/eigger/stash)
