# HA Apps by eigger

Home Assistant [App](https://www.home-assistant.io/apps/) repository (formerly add-ons).

## Apps

| App | Description |
|-----|-------------|
| [ESPHome OTA Publisher](esphome_ota/) | Serve ESPHome firmware for `http_request` OTA via `/local` — no ports opened |
| [Garage](garage/) | Self-hosted car management (Postgres + API + Web all-in-one, upstream release images), via Ingress or host port — `amd64` only |
| [Stash](stash/) | Self-hosted home inventory & barcode manager (same all-in-one packaging), via Ingress or host port — `amd64` only |
| [Drop](drop/) | Self-hosted file sharing between phone and PC (same all-in-one packaging), host port only — `amd64` only |
| [Kibble](kibble/) | Self-hosted pet care journal (same all-in-one packaging), host port only — `amd64` only |

Temporarily disabled (folder kept, prefixed with `.` so the Supervisor no longer
discovers it for new installs — already-installed users are unaffected):
Tesseract OCR.

## Install

1. **Settings → Apps → ⋮ → Repositories**
2. Add repository URL: `https://github.com/eigger/hassio-apps`
3. Install the app you want

## Upstream

- [eigger/stash](https://github.com/eigger/stash)
- [eigger/garage](https://github.com/eigger/garage)
- [eigger/drop](https://github.com/eigger/drop)
- [eigger/kibble](https://github.com/eigger/kibble)
