# Garage

Self-hosted car management as a Home Assistant app.

## How to use

1. Start the app.
2. Open the **Garage** entry in the sidebar, or go to `http://<ha-ip>:3081`.
3. Create the first admin account, then configure vehicles and API keys in the UI.

Data persists under `/data`.

## Ingress and the host port

Both work. The sidebar entry goes through Home Assistant's Ingress, which is also what
makes the app reachable from your Home Assistant external URL — the host port is only
reachable on the LAN unless you expose it yourself.

Ingress serves the app under `/api/hassio_ingress/<token>/`, and that token is handed out
per installation. Upstream builds the web image with a placeholder base path and rewrites
it at start-up, so this app looks its Ingress entry up from the Supervisor and passes it
in. If that lookup fails the app still starts and serves on the host port; the log says so
and the sidebar entry will not render.

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
