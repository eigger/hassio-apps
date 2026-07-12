# Stash

Self-hosted home inventory & barcode manager as a Home Assistant app.

## How to use

1. Start the app.
2. Open **Open Web UI** or go to `http://<ha-ip>:3080`.
3. Create the first admin account, then configure integrations in the Stash settings UI.

Data persists under `/data`. Ingress is not used (Next.js absolute paths break under HA’s subpath proxy).
