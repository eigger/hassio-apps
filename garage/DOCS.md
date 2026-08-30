# Garage

Self-hosted car management as a Home Assistant app.

## How to use

1. Start the app.
2. Open **Open Web UI** or go to `http://<ha-ip>:3081`.
3. Create the first admin account, then configure vehicles and API keys in the UI.

Data persists under `/data`. Ingress is not used (Next.js absolute paths break under HA’s subpath proxy).

## Options

There are none, on purpose. Integration keys — Opinet, 천안사랑카드, the EV charger
API, and the Web Push (VAPID) pair, which the app can generate for you — belong in
Garage's own **/integrations** screen. Those values are stored in its database and
take priority over anything in the environment, so configuring them twice would
only create a second, silently ignored copy.

The Postgres password and JWT secret are generated on first start and kept under
`/data/secrets`.

## Requirements

`amd64` only — the upstream `garage-api` / `garage-web` images are published for
linux/amd64 alone.
