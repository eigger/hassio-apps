# ESPHome OTA Publisher

[한국어 문서](README.ko.md)

For ESPHome devices that ESPHome's own local/mDNS OTA can't reach — typically
because they're outside your home network and only reachable through your
Home Assistant's remote/cloud-tunnel address. A device on the same network as
Home Assistant doesn't need this: just use ESPHome's built-in OTA.

It publishes firmware, its MD5, and an ESP-Web-Tools manifest into
`<config>/www/`, which Home Assistant already serves unauthenticated at
`/local/` — reachable over both your internal address and your external
tunnel, with nothing to open on this add-on's side.

```
                                                <config>/www/esphome_ota/
                                                        │
                              https://<your-external-address>/local/esphome_ota/…
                                                        ▼
                                                 your remote devices
```

There are two ways to get firmware in there:

## A. Manual publish — no other setup required

Download `firmware.ota.bin` from the ESPHome dashboard yourself (its "OTA
format" download), then open this add-on's panel → **Manual publish** →
fill in the node name, chip family, and version, and upload the file. Nothing
on the ESPHome side needs to change for this.

## B. Build & publish from here — needs a setting on ESPHome's side

This add-on can drive the ESPHome Device Builder add-on directly (the same
API its own dashboard UI uses) so you can build and publish in one click. Its
normal access path — the HA sidebar / Ingress — is locked to loopback and the
Supervisor by design; a sibling add-on can't reach it there. Reaching it
requires ESPHome's *public* port instead, which means mapping port `6052` and
turning on `leave_front_door_open` in the **ESPHome** add-on's own settings.
That opens ESPHome's dashboard — configs, `secrets.yaml`, rebuild/reflash —
unauthenticated on your LAN (not through any external tunnel, just your local
network). See [DOCS.md](DOCS.md#required-esphome-add-on-setting) before
turning this on if that trade-off matters to you. Skip it and use A instead if
it doesn't sound worth it.

## Why not just read ESPHome's build folder?

You can't. When ESPHome runs as an add-on its `CORE.data_dir` is pinned to
`/data` — the add-on's private volume — so the compiled binaries never appear
under `/config/esphome`, and the Supervisor offers no mapping that reaches
another add-on's data. Only the YAML sources are shared.

## What you get

Two ESPHome packages are generated into `<config>/esphome/ota_server/`:

| Package | Gives you | Needs |
|---|---|---|
| `flash_button.yaml` **(recommended default)** | A **button** that always installs the latest published build | Nothing |
| `update.yaml` | An **Update entity** in Home Assistant with an Install button | An `esphome.project` block with a `version` you bump |

Use one or the other — both define `ota:`, so including both is a conflict.

Start with `flash_button.yaml` unless you specifically want an Update entity
in Home Assistant. `update.yaml` fetches a JSON manifest first and only
downloads firmware after parsing it; `flash_button.yaml` never parses
anything, it just downloads a `.bin` and checks its MD5 — one fewer thing
for a proxy/CDN sitting in front of Home Assistant to interfere with. If
`update.yaml` logs `Failed to parse JSON from .../<node>.json`, switch that
device to `flash_button.yaml` — see
[DOCS.md](DOCS.md#failed-to-parse-json-from-the-manifest-updateyaml-only).

Both packages cache-bust their firmware URL now (a `?v=<md5>` on the
manifest's binary path for `update.yaml`, a random `?r=` on every press for
`flash_button.yaml`), so a caching proxy or CDN in front of Home Assistant
(e.g. a Cloudflare tunnel) can't serve back a stale `.ota.bin` after a
republish. If a device is still running an older `flash_button.yaml`
compiled before this, see
[DOCS.md](DOCS.md#md5-mismatch-during-ota-aborting-due-to-md5-mismatch) —
recompiling and reflashing it once (any way that currently works) picks up
the fix.

## Install

1. Add this repository to Home Assistant → Settings → Add-ons → Repositories
2. Install **ESPHome OTA Publisher** and start it
3. If the add-on asks you to restart Home Assistant, do it once (the `/local`
   static path is registered at startup)
4. Check the add-on's panel for a banner about `base_url` — it auto-fills from
   Home Assistant's configured external URL (Settings → System → Network); if
   you haven't set one there, set `base_url` in this add-on's options directly
5. Publish a device (manually, or after enabling ESPHome's public port — see
   above), then paste the shown YAML snippet into that device's config

See [DOCS.md](DOCS.md) for options and troubleshooting.
