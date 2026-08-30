# Garage

Self-hosted car management as a Home Assistant app.

## How to use

1. Start the app.
2. Open **Open Web UI** or go to `http://<ha-ip>:3081`.
3. Create the first admin account, then configure vehicles and API keys in the UI.

Data persists under `/data`. Ingress is not used (Next.js absolute paths break under HA’s subpath proxy).

## Options

Every option is optional and empty by default; the app is fully usable without them.
They map 1:1 onto the env vars upstream's `docker-compose.prod.yml` passes to the API:
`opinet_api_key` (`OPINET_API_KEY`), `cheonan_card_enabled` (`CHEONAN_CARD_ENABLED`),
`ev_charger_api_key` (`EV_CHARGER_API_KEY`) and `vapid_public_key` /
`vapid_private_key` / `vapid_subject` (`VAPID_*`, for web push reminders).

Changing an option restarts the app and rewrites `/data/secrets/runtime.env`;
the generated Postgres password and JWT secret are kept.

## Requirements

`amd64` only — the upstream `garage-api` / `garage-web` images are published for
linux/amd64 alone.
