# ESPHome OTA Server

Publishes ESPHome firmware so devices can update themselves over plain HTTP
with the `http_request` OTA platform — no manual file copying, and this add-on
itself opens no ports.

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

**Required on the ESPHome side:** its dashboard's normal access path (the HA
sidebar / Ingress) is locked to loopback and the Supervisor by design — a
sibling add-on can't reach it there. Reaching it instead requires ESPHome's
*public* port, which means mapping port 6052 and turning on
`leave_front_door_open` in the **ESPHome** add-on's own settings. That opens
ESPHome's dashboard — configs, `secrets.yaml`, rebuild/reflash — unauthenticated
on your LAN (not through any external tunnel, just your local network). See
[DOCS.md](DOCS.md#required-esphome-add-on-setting) before installing if that
trade-off matters to you.

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

1. In the **ESPHome Device Builder** add-on: Network tab → map `6052/tcp` to
   `6052`, then in its options turn on `leave_front_door_open` and restart it
2. Add this repository to Home Assistant → Settings → Add-ons → Repositories
3. Install **ESPHome OTA Server** and start it
4. If the add-on asks you to restart Home Assistant, do it once (the `/local`
   static path is registered at startup)
5. Open the add-on's panel, hit **Build & publish** on a device, then paste
   the shown snippet into that device's YAML

See [DOCS.md](DOCS.md) for options and troubleshooting.
