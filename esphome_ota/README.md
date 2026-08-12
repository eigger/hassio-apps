# ESPHome OTA Server

Publishes ESPHome firmware so devices can update themselves over plain HTTP
with the `http_request` OTA platform — no extra ports, no manual file copying.

It pulls `firmware.ota.bin` from the **ESPHome Device Builder** add-on using the
same API the dashboard's own frontend uses, then writes the binary, its MD5, and
an ESP-Web-Tools manifest into `<config>/www/`, which Home Assistant already
serves unauthenticated at `/local/`.

```
ESPHome Device Builder  ──WS API──▶  this add-on  ──▶  <config>/www/esphome_ota/
                                                             │
                                          http://<ha>:8123/local/esphome_ota/…
                                                             ▼
                                                        your devices
```

## Why not just read ESPHome's build folder?

You can't. When ESPHome runs as an add-on its `CORE.data_dir` is pinned to
`/data` — the add-on's private volume — so the compiled binaries never appear
under `/config/esphome`, and the Supervisor offers no mapping that reaches
another add-on's data. Only the YAML sources are shared. Going through the
dashboard API is the supported path, and it is exactly what pressing *Install*
in the dashboard does.

## What you get

Two ESPHome packages are generated into `<config>/esphome/ota_server/`:

| Package | Gives you | Needs |
|---|---|---|
| `update.yaml` | An **Update entity** in Home Assistant with an Install button | An `esphome.project` block with a `version` you bump |
| `flash_button.yaml` | A **button** that always installs the latest published build | Nothing |

Use one or the other — both define `ota:`, so including both is a conflict.

## Install

1. Add this repository to Home Assistant → Settings → Add-ons → Repositories
2. Install **ESPHome OTA Server** and start it
3. If the add-on asks you to restart Home Assistant, do it once (the `/local`
   static path is registered at startup)
4. Open the add-on's panel, hit **빌드 후 게시** on a device, then paste the
   shown snippet into that device's YAML

See [DOCS.md](DOCS.md) for options and troubleshooting.
