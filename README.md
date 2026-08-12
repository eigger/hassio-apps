# HA Apps by eigger

Home Assistant [App](https://www.home-assistant.io/apps/) repository (formerly add-ons).

## Apps

| App | Description |
|-----|-------------|
| [ESPHome OTA Server](esphome_ota/) | Serve ESPHome firmware for `http_request` OTA via `/local` — no ports opened |

Temporarily disabled (folders kept, prefixed with `.` so the Supervisor no longer
discovers them for new installs — already-installed users are unaffected):
Tesseract OCR, Stash, Garage.

## Install

1. **Settings → Apps → ⋮ → Repositories**
2. Add repository URL: `https://github.com/eigger/hassio-apps`
3. Install the app you want

## Upstream

- [eigger/stash](https://github.com/eigger/stash)
- [eigger/garage](https://github.com/eigger/garage)
