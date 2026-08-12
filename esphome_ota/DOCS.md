# ESPHome OTA Server — Documentation

## How it works

1. The add-on finds the running ESPHome Device Builder add-on through the
   Supervisor and connects to its WebSocket API. It prefers the add-on's
   **ingress port**, because device-builder binds that site to `127.0.0.1` and
   the Supervisor gateway `172.30.32.1` and skips authentication there — so no
   credentials are needed and the ESPHome dashboard stays closed to the LAN.
2. On demand it runs `firmware/compile` → `firmware/follow_job` →
   `firmware/download_token` → `GET /api/firmware/download`, which is the same
   sequence the dashboard frontend performs.
3. It computes the MD5, works out the `chipFamily`, and writes three files into
   `<config>/www/<publish_dir>/`.
4. Home Assistant serves those at `/local/<publish_dir>/…` with no
   authentication, over whatever address the device can reach it on.

## Options

| Option | Default | Meaning |
|---|---|---|
| `dashboard_url` | *(auto)* | Override the ESPHome dashboard base URL, e.g. `http://172.30.32.1:6052`. Leave empty to auto-detect. |
| `dashboard_token` | *(empty)* | Only needed for a dashboard started with `ESPHOME_USERNAME`/`ESPHOME_PASSWORD`. The HA add-on does not use one. |
| `publish_dir` | `esphome_ota` | Folder under `<config>/www/`, and therefore the path under `/local/`. |
| `base_url` | *(auto)* | How your devices reach Home Assistant, e.g. `http://192.168.0.10:8123`. Auto-detected from the host's primary LAN address. Only used to fill in the generated packages. |
| `log_level` | `info` | `debug` prints every dashboard frame. |

## Published files

For a device `livingroom.yaml`:

```
<config>/www/esphome_ota/livingroom.ota.bin       the firmware
<config>/www/esphome_ota/livingroom.ota.bin.md5   hex digest (for md5_url)
<config>/www/esphome_ota/livingroom.json          manifest (for update.http_request)
```

The manifest's `ota.path` is **relative** and carries a `?v=<md5 prefix>`:

```json
{"name":"Living Room","version":"1.0.0","builds":[{"chipFamily":"ESP32-C3",
 "ota":{"md5":"5bf1…","path":"livingroom.ota.bin?v=5bf1f6e2","summary":"…"}}]}
```

Relative, because ESPHome resolves it against the manifest's own URL — so the
same files work whether the device fetched the manifest from a LAN address or
through a remote tunnel, with nothing to rewrite.

Cache-busted, because Home Assistant stamps a 31-day `Cache-Control` on
everything under `/local`. Straight over the LAN that is harmless (the ESP
caches nothing), but a proxy in front of Home Assistant — a Cloudflare tunnel,
for instance — caches `.bin` by default and would happily serve month-old
firmware. `.json` is not cached by default, so the manifest stays fresh and
points at a new URL after every build.

Binaries are written to a temp file and `os.replace`d into position. A rename
swaps the directory entry while an in-flight download keeps reading the old
inode, so republishing while a device is downloading cannot corrupt its update.

## The two packages

### A. Update entity — `ota_server/update.yaml`

```yaml
substitutions:
  ota_device: livingroom

packages:
  ota: !include ota_server/update.yaml

esphome:
  project:
    name: "you.something"
    version: "1.0.0"      # bump to publish an update
```

The device reports `ESPHOME_PROJECT_VERSION` as its current version and
compares it with the manifest's `version`. **Without an `esphome.project`
block** the device falls back to reporting the ESPHome release string, so the
add-on publishes that as the manifest version too — meaning an update only ever
appears when you upgrade ESPHome itself, not when you change your config. The
UI flags devices in that state.

### B. Force-install button — `ota_server/flash_button.yaml`

```yaml
substitutions:
  ota_device: livingroom

packages:
  ota: !include ota_server/flash_button.yaml
```

No version tracking. Pressing the button runs `ota.http_request.flash` against
the fixed `.ota.bin` URL with `md5_url` for verification; if the digest does not
match what was downloaded, the device keeps its existing firmware.

Because that URL is fixed it has no cache buster — fine over the LAN, but for
devices that would fetch through a caching proxy prefer package A.

## Troubleshooting

**"Restart Home Assistant once."** — `/local` is registered once at startup,
behind an `isdir` check on the `www` folder. If the add-on had to create that
folder, Home Assistant does not know about it yet.

**"Could not find the ESPHome dashboard."** — the ESPHome add-on must be
running. If auto-detection still fails, map port 6052 in the ESPHome add-on's
Network settings, turn on its `leave_front_door_open` option, and set
`dashboard_url: http://172.30.32.1:6052`.

**Devices list returns HTTP 502** — the add-on log now includes the real
`DashboardError` message for this (a warning logged right where the 502 is
returned). Common causes: the ESPHome add-on isn't actually reachable at the
resolved `dashboard_url` (check the add-on log's "Found ESPHome dashboard…"
line against what's actually running), or the WebSocket connection dropped
mid-request. Re-check the add-on log after reproducing — the error text there
is the same one shown in the UI, not a generic proxy failure.

**The update entity never appears** — check `chipFamily` in the UI. ESPHome
matches it against `ESPHOME_VARIANT` with an exact string comparison and
reports nothing at all on a mismatch. LibreTiny targets (BK72xx, RTL87xx) are
not supported; their variant strings are per-chip and the add-on cannot derive
them.

**Backups grew** — `<config>/www` is included in Home Assistant backups, at
roughly 1–2 MB per published device. Remove a device's files with the delete
endpoint or by clearing the folder.

**Firmware is world-readable** — `/local` has no authentication, by design.
That is what makes it reachable from a device that cannot log in. Anything you
publish is readable by anything that can reach Home Assistant's HTTP port.
