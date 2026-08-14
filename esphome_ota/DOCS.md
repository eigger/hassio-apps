# ESPHome OTA Publisher — Documentation

[한국어 문서](DOCS.ko.md)

## Manual publish (Recommended)

The table shows **registered** devices. A row stays even before you upload
firmware, so leaving to compile in ESPHome does not lose it.

1. Pick the YAML, set the version, and **Register**.
2. Click **`+ Apply OTA`** on that row to automatically inject the OTA package into the device YAML (or copy the snippet if you prefer manual editing).
3. Compile in ESPHome.
4. In ESPHome: **Install → Advanced options → Download firmware binary →
   OTA update**. Drag & drop that `.bin` file onto the row or click **`Publish`** to upload.
   Use OTA update, not Modern/Factory.

The published slug is the YAML filename (`livingroom.yaml` →
`livingroom.ota.bin` / `livingroom.json`). Chip family is read from the
image header. **YAML Config** shows whether the OTA package is injected into the device YAML.
**YAML Version** is the `esphome.project.version` that will be compiled into the firmware via the wrapper
(editable directly in that column or snippet panel). **Published Firmware** is the version currently
served on `/local`. After a publish, YAML Version automatically advances so the next compile is a new update.

No connection to ESPHome is needed for this; it goes straight to
`Publisher.publish`, the same code the automatic path uses at the end.

Use this if you don't want to open ESPHome's public port (see below), or just
for a one-off device.

Published rows can be uploaded again, injected/ejected via one click, copied as a YAML snippet, or
**Delete**d. If the dashboard is reachable for a published node, Build &
publish stays available on that row.

## Required ESPHome add-on setting (only for the automatic Build & publish path)

The manual path above needs none of this. This section only applies if you
want this add-on to build and pull firmware directly from ESPHome Device
Builder's WebSocket API. Its
normal access path — the HA sidebar / Ingress — is a dead end for that: the
ingress site is guarded by `ingress_peer_guard` middleware
(`esphome_device_builder/helpers/auth.py`) that only admits connections whose
TCP peer is loopback or the Supervisor container's own fixed address
(`172.30.32.2`). Ingress exists to let HA's authenticated-browser proxy
through — not for one add-on to call another. Any other source IP, including
a sibling add-on reaching the same bound port directly, gets a flat HTTP 403
on the WebSocket handshake, no matter which address or port it's dialed on.

The only other door in is ESPHome's *public* port, and device-builder only
binds that when **both** are true (either alone leaves it unbound):

1. Network tab → `6052/tcp` mapped to a host port
2. Options → `leave_front_door_open` turned on

With both set, that port serves the full dashboard with no authentication at
all — configs, `secrets.yaml` (Wi-Fi credentials), rebuild/reflash — to
anything that can reach it. Unlike this add-on's own `/local` publishing,
this is not scoped to firmware files, and it doesn't ride the external
cloud-tunnel path — only your LAN sees it, same as this add-on's `/local`
files today. If your LAN isn't a zone you're comfortable with unauthenticated
services in, don't enable this; the add-on will just keep logging that it
can't find the dashboard.

## How it works

1. Resolves `base_url` (see the Options table below) — HA's configured
   external URL via `GET /core/api/config` (needs `homeassistant_api: true`,
   already set) unless overridden, since that's the address a device outside
   the LAN actually needs.
2. **Automatic path:** finds the ESPHome add-on's mapped public port through
   the Supervisor (`GET /addons`, then `/addons/<slug>/info`) and connects its
   WebSocket API there — see above for why the ingress port doesn't work for
   this. Runs `firmware/compile` → `firmware/follow_job` →
   `firmware/download_token` → `GET /api/firmware/download`, the same
   sequence the dashboard frontend performs. **Manual path:** the uploaded
   file is used as-is.
3. Either way: computes the MD5, works out the `chipFamily`, and writes three
   files into `<config>/www/<publish_dir>/`.
4. Home Assistant serves those at `/local/<publish_dir>/…` with no
   authentication, over whatever address the device can reach it on.

## Options

| Option | Default | Meaning |
|---|---|---|
| `dashboard_url` | *(auto)* | Override the ESPHome dashboard base URL, e.g. `http://172.30.32.1:6052` (the mapped public port, not the ingress port — see above). Leave empty to auto-detect. |
| `dashboard_token` | *(empty)* | Only needed for a dashboard started with `ESPHOME_USERNAME`/`ESPHOME_PASSWORD`. |
| `publish_dir` | `esphome_ota` | Folder under `<config>/www/`, and therefore the path under `/local/`. |
| `base_url` | *(auto)* | How your devices reach Home Assistant, e.g. `https://your-tunnel-domain`. Resolution order: this option, if set → HA's configured external URL (Settings → System → Network) → the host's LAN address as a last resort (logged as a warning — this only works for devices on the same LAN, which generally don't need this add-on at all). Only used to fill in the generated packages. |
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

## The packages — `ota_server/*.yaml`

Three files, each named for exactly what it contains:

| File | Contains |
|---|---|
| `update.yaml` — **recommended** | Update entity only |
| `flash_button.yaml` — fallback | Force-install button only |
| `ota.yaml` | Both — only exists because `update.yaml` and `flash_button.yaml` can't be `!include`d together (both declare `http_request:`/`ota:`, and ESPHome doesn't merge two packages' same-named top-level keys) |

```yaml
packages:
  ota: !include ota_server/devices/livingroom.yaml
```

The wrapper (`ota_server/devices/<yaml-stem>.yaml`) sets `ota_device`, the
OTA entities, and `esphome.project`. You do not paste a project block or
bump a version in the device YAML. Set the version when you register; edit
it in the Next column. After a publish the wrapper is raised so the next
compile is a new update. The shared packages also enable `safe_mode:` —
`http_request` OTA does not turn that on the way `platform: esphome` does.

For Update-only or button-only, include `livingroom.update.yaml` or
`livingroom.button.yaml` in the same folder. The older form
(`substitutions.ota_device` + `!include ota_server/update.yaml`) still works.

**The Update entity is the recommended default** — version tracking, and an
Install button in Home Assistant. It fetches and parses a JSON manifest
first, which is one more thing a proxy/CDN in front of Home Assistant can
interfere with on some configurations (see
[Troubleshooting](#failed-to-parse-json-from-the-manifest-update-entity-only)).
If you hit that specific failure, switch the `!include` to the `.button.yaml`
wrapper — it never parses anything, at the cost of
no version tracking. Want both entities on one device? Use the stem wrapper
(`devices/livingroom.yaml`) instead of either.

### Update entity

The device reports `ESPHOME_PROJECT_VERSION` as its current version and
compares it with the manifest's `version`. The generated wrapper always
supplies `esphome.project`, so you do not add that block to the device YAML.
If a config still uses the legacy `ota_device` include and has no project
block, the device falls back to the ESPHome release string — an update then
only appears when you upgrade ESPHome itself. The button still works either
way.

Pressing Install only downloads if the device's `update:` state is already
`AVAILABLE` — that state only comes from a prior successful manifest fetch
(automatic, every `update_interval`, or via the `update.check` action).
`update.check` is asynchronous, so calling it and then immediately calling
`update.perform` from the same button press can fire the install before the
fetch resolves. Use `on_update_available` on the `update:` entity instead,
so the install only happens after a fetch actually confirms one is
available:

```yaml
button:
  - platform: template
    name: Check for update
    on_press:
      - update.check: ota_update

update:
  - id: !extend ota_update
    on_update_available:
      - update.perform: ota_update
```

### Force-install button

No version tracking. Pressing the button runs `ota.http_request.flash` against
the `.ota.bin` URL with `md5_url` for verification; if the digest does not
match what was downloaded, the device keeps its existing firmware.

`url`/`md5_url` are lambdas that append a random `?r=<random_uint32()>` on
every press, so each press is a fresh cache miss for any proxy or CDN in
front of Home Assistant — there is no fixed URL for it to have cached a
stale copy of in the first place.

The generated button's id is `ota_flash_button`. Trigger it from something
else in the device YAML with `button.press` instead of duplicating the
`ota.http_request.flash` call — e.g. a physical GPIO button that flashes the
latest published firmware when pressed:

```yaml
button:
  - platform: gpio
    pin: GPIO0
    name: Flash Button
    on_press:
      - button.press: ota_flash_button
```

### Overriding the address for one device

The package defines an `ota_base_url` substitution defaulting to the add-on's
configured `base_url`. ESPHome applies the main config's `substitutions:` over
a package's same-named ones, so a device that needs a different address —
say, a second remote site — can override it without touching the generated
files:

```yaml
substitutions:
  ota_base_url: https://second-site.example

packages:
  ota: !include ota_server/devices/livingroom.yaml
```

## Troubleshooting

**"Restart Home Assistant once."** — `/local` is registered once at startup,
behind an `isdir` check on the `www` folder. If the add-on had to create that
folder, Home Assistant does not know about it yet.

**"Could not find the ESPHome dashboard."** — the ESPHome add-on must be
running, with port 6052 mapped and `leave_front_door_open` turned on (see
[Required ESPHome add-on setting](#required-esphome-add-on-setting) above —
without both, its public port stays unbound, and there's nothing else this
add-on can reach). Still failing? Set `dashboard_url` directly, e.g.
`http://172.30.32.1:6052`.

**Devices list returns HTTP 502 with "HTTP 403" in the message** — this add-on
tried the ingress port instead of the public one (only possible if
`dashboard_url` was set by hand). Point it at the mapped public port instead.

**Devices list returns HTTP 502, other reason** — the add-on log now includes
the real `DashboardError` message for this (a warning logged right where the
502 is returned). Re-check the log after reproducing — the error text there is
the same one shown in the UI, not a generic proxy failure.

**The update entity never appears** — check `chipFamily` in the UI. ESPHome
matches it against `ESPHOME_VARIANT` with an exact string comparison and
reports nothing at all on a mismatch — on the device the only sign is
`Failed to parse JSON from …` in the log, and an update entity stuck on
*unknown* in Home Assistant. The published value comes from the image header's
chip id; if the add-on doesn't recognise that id it now refuses to publish
rather than guessing (the log names the id — file it as a bug). LibreTiny
targets (BK72xx, RTL87xx) are not supported; their variant strings are
per-chip and the add-on cannot derive them.

**Backups grew** — `<config>/www` is included in Home Assistant backups, at
roughly 1–2 MB per published device. Remove a device's files with the delete
endpoint or by clearing the folder.

**Firmware is world-readable** — `/local` has no authentication, by design.
That is what makes it reachable from a device that cannot log in. Anything you
publish is readable by anything that can reach Home Assistant's HTTP port.

**MD5 mismatch during OTA (`Aborting due to MD5 mismatch`)** — usually a
caching proxy in front of Home Assistant (a Cloudflare tunnel, most
commonly) serving a stale `.ota.bin` after a republish. The generated
package now cache-busts the firmware URL (see
[above](#force-install-button)), so a freshly regenerated `ota.yaml`
shouldn't hit this — this is for a device still running firmware compiled
from the old fixed-URL `flash_button.yaml` (pre-0.3.5), or a caching layer
that's ignoring query strings entirely (rare, but some CDNs can be
configured that way). Confirm it by comparing what the origin actually has
right now against what's really being served:

```bash
curl -s "$BASE/local/$PUBLISH_DIR/$NODE.ota.bin.md5"
curl -s "$BASE/local/$PUBLISH_DIR/$NODE.ota.bin" | md5sum
```

If those two disagree, check the response headers (`curl -sD -`) for
`cf-cache-status: HIT` (or an equivalent proxy cache header) and a stale
`age`/`last-modified` on the `.bin` request — that confirms a cache, not the
add-on, is serving old bytes. Fix it:

- **Recompile and reflash the device once**, by whatever method currently
  works (USB, or a manual firmware install through the ESPHome dashboard).
  That picks up the new package with its randomized `?r=`, which
  ends the problem for every press after.
- **If the CDN ignores query strings for caching**, add an explicit cache
  bypass rule instead. In Cloudflare: Rules → Cache Rules → match the path
  (e.g. `contains` `.ota.bin`) → Cache eligibility: **Bypass cache**.

A one-off already-stuck cache just needs a manual purge of that specific
`.ota.bin` URL to unblock the device immediately.

<a id="failed-to-parse-json-from-the-manifest-update-entity-only"></a>

**"Failed to parse JSON from ...`/<node>.json`" (Update entity only)** — the
device successfully reached `source:` but what it got back didn't parse as
JSON. Confirmed in the field on a Cloudflare-tunneled `base_url`: the file on
disk was valid every time it was checked from outside (`curl -s
".../<node>.json"`), yet the device's own fetch kept failing, immediately
and repeatably — not a caching/staleness symptom like the MD5 mismatch
above, and not tied to a republish.

Leading suspect, unconfirmed: response compression. `curl -H
"Accept-Encoding: gzip, deflate" ".../<node>.json"` gets back
`content-encoding: gzip` and an actually-gzipped body from this add-on's
Cloudflare-fronted `/local` — confirming Cloudflare *can* and *will* gzip
this response if a request asks for it. ESPHome's `http_request` component
does not decompress gzip; if the device's request ends up asking for
compression by any path (its own defaults, a network middlebox, whatever's
between it and Cloudflare) it would receive compressed bytes and hand them
to the JSON parser as-is — exactly this error, and exactly this
reachable-but-unparseable pattern.

To test: Cloudflare dashboard → **Speed → Optimization → Brotli** → turn
off, then retry the device's manifest check. If that fixes it, compression
was the cause; either leave it off for this zone (a firmware manifest is a
few hundred bytes, compression buys nothing) or, on a plan with
Configuration Rules / Response Header Transform Rules, scope the exclusion
to `/local/*` instead of the whole zone.

Simplest fix regardless of root cause: **use the force-install button
instead of the Update entity's Install**. It downloads `.ota.bin` and reads
`.ota.bin.md5` as plain text — no JSON parsing step for a compressed or
otherwise-mangled response to break.

**Manual publish rejects the chip family** — on **Auto** this means the
uploaded file's header carried no chip id the add-on could read: either it
isn't an ESP32 image (ESP8266/RP2040 — pick the family from the dropdown) or
it isn't a `.ota.bin` at all. A hand-picked family is used as-is only in that
case; whenever the header does carry a chip id, it wins over the dropdown, so
an ESP32-C3 binary can no longer be published as `ESP32` by mistake.
