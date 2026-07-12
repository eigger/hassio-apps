# Stash (Home Assistant App)

Runs [stash](https://github.com/eigger/stash) (home inventory & barcode manager) **all-in-one inside one app**, similar to an LXC:

- PostgreSQL 16
- Stash API (`ghcr.io/eigger/stash-api`)
- Stash Web (`ghcr.io/eigger/stash-web`)
- Nginx (Ingress `:8099`, routes `/api`, `/health`, and the UI)

## Install

1. HA → **Settings → Apps → ⋮ → Repositories**
2. Add this repository URL
3. Install **Stash** and start it
4. Open **Stash** from the sidebar (Ingress)

On first launch, create an admin account via **Create first admin** on `/login`.

## Options

| Option | Description |
|--------|-------------|
| `jwt_secret` | Auto-generated and stored under `/data` if left empty |
| `app_public_url` | Public URL for self-issued QR deep-links |
| `upcitemdb_api_key` | Optional |
| `inventory_webhook_url` | Optional (e.g. Home Assistant automations) |

Data, uploads, and secrets persist in the app `/data` directory.

## Ingress notes

Ingress is proxied under a Supervisor subpath. Absolute root paths (e.g. `/api`) in the web app can break under Ingress. If that happens, map host port `3080/tcp` for direct access, or adapt the app to relative paths / `basePath`.

Upstream: [eigger/stash](https://github.com/eigger/stash)
