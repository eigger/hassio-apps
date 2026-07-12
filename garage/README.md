# Garage (Home Assistant App)

Runs [garage](https://github.com/eigger/garage) (car management) **all-in-one inside one app**, similar to an LXC:

- PostgreSQL 16
- Garage API (`ghcr.io/eigger/garage-api`)
- Garage Web (`ghcr.io/eigger/garage-web`)
- Nginx (Ingress `:8099`, routes `/api`, `/health`, and the UI)

## Install

1. HA → **Settings → Apps → ⋮ → Repositories**
2. Add this repository URL
3. Install **Garage** and start it
4. Open **Garage** from the sidebar (Ingress)

On first launch, create an admin account via **Create first admin** on `/login`.

## Options

| Option | Description |
|--------|-------------|
| `jwt_secret` | Auto-generated and stored under `/data` if left empty |
| `opinet_api_key` | Optional (fuel stations) |
| `vapid_*` | Optional (Web Push) |

Data, uploads, and secrets persist in the app `/data` directory.

## Ingress notes

Ingress is proxied under a Supervisor subpath. Absolute root paths in the web app can break under Ingress. If that happens, map host port `3080/tcp` for direct access.

Upstream: [eigger/garage](https://github.com/eigger/garage)
