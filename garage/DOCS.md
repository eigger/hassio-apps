# Garage

Self-hosted car management as a Home Assistant app.

## How to use

1. Start the app.
2. Open **Open Web UI** or go to `http://<ha-ip>:3081`.
3. Create the first admin account, then configure vehicles and API keys in the UI.

Data persists under `/data`. Ingress is not used (Next.js absolute paths break under HA’s subpath proxy).
