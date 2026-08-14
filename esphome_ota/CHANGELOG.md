# Changelog

## 0.5.2

Register and publish are separate. The list is registered devices, not a
scratch form that disappears when you go compile in ESPHome.

- **Register** a YAML and version first — that row stays in the table.
- Copy the snippet from the row, compile, then **Publish** the `.bin` on
  the same row (or drop it there). Per-device wrapper YAML is created then
  (and when you open the snippet to compile), not for every YAML on startup.
  Deleting a device removes those files too.
- Already-published devices are treated as registered, so existing lists
  keep working.

## 0.5.1

The easy path is pick YAML → paste snippet → compile → upload. You do not
set `project.version` (or `ota_device`) on the device.

- Generated wrappers always include `esphome.project`. Version starts at
  `1.0.0` and is raised when you open the snippet after that build is
  already published, so the next compile is a new update. You can edit the
  version in the form before compile; that value is written to the wrapper.
  Re-uploading the same `.bin` does not jump the manifest ahead of the
  firmware.
- The snippet is only the include. Copy lives in the publish form, in the
  same order as the work.
- Generic `esp32:` YAML no longer locks the chip dropdown to classic ESP32;
  the image header still decides C3/S3/….

## 0.5.0

Manual publish no longer asks you to type a node name or set `ota_device` on
the device.

- Manual publish picks a YAML file, or **Custom name** for the previous
  typed `ota_device` slug. Unpublished configs are not table rows.
- Generated per-device wrappers set `ota_device`. `esphome.project` is copied
  from the device YAML when present; otherwise omitted so firmware reports
  the ESPHome release (the row tooltip says so). The snippet is
  `packages: ota: !include ota_server/devices/<stem>.yaml`.
  Names with no local YAML still get the legacy `ota_device` snippet.
- Publish version is what the firmware reports when the device YAML has
  `project.version`. Otherwise the dashboard ESPHome release is only a
  default — a typed version (old compiler, published-only, Custom name)
  is kept. The Version field is read-only only when the YAML declares
  `project.version`.

## 0.4.3

**`update.yaml` and `flash_button.yaml` are genuinely single-entity again.**
Since the 0.4.0 merge they'd been written as identical copies of the
combined `ota.yaml` — so `!include`-ing either name silently gave you both
entities, not just the one its filename promised. Reverted: `update.yaml`
now contains only the Update entity, `flash_button.yaml` only the button;
`ota.yaml` remains for a device that wants both (and is the only way to get
both — the two single-entity files can't be `!include`d together, both
declare `http_request:`/`ota:`).

The "Advanced: individual entities" section added last version (0.4.2) was
built against the old identical-copies behavior and had it backwards — it
inlined raw single-entity YAML instead of using these files, and the
Update-only example was missing its `esphome.project` block entirely. Now
uses clean `packages: ota: !include ota_server/update.yaml` /
`flash_button.yaml`, matching the main example's style, with the project
block included.

README/DOCS (both languages) updated to describe three distinct files
instead of one file with two aliases.

## 0.4.2

- **Update entity promoted to the recommended default** across README/DOCS
  (both languages) and the generated package's comments — reordered ahead
  of the force-install button everywhere, with the button now framed as the
  fallback for the specific JSON-parse failure mode, not the default choice.
  The failure mode itself is unchanged and still documented; this is a
  documentation reframe, not a behavior change.
- **YAML snippet panel now also shows the pre-merge single-entity examples**
  (Update-only, button-only) in a collapsed "Advanced: individual entities"
  section — reference only, not new generated files. Fixed a real bug found
  while building this: the two examples each had their own `substitutions:`
  block, which is a duplicate top-level key when pasted as one document —
  YAML silently keeps only the last one, so `ota_device` would have been
  dropped. Merged into a single block per example.
- **The `esphome.project` example now reflects reality**: `version` defaults
  to whatever's actually published for that device (the number to bump
  *from*) instead of always resetting to a fixed `1.0.0`, and
  `project.name` defaults to `local.<node>` instead of a fixed personal
  placeholder — every device gets a distinct name with nothing to remember
  to edit.
- **Published date/time now shown** in the device table, next to the MD5 on
  the existing second line (no new row height).

## 0.4.1

- **Fixed `chipFamily` for ESP32-P4 and ESP32-C5.** Their `esp_chip_id_t`
  values were missing from the image-header table, so detection fell through
  to the ESPHome dashboard's `target_platform` — which reports the *component*
  (`esp32`) for every variant and therefore published `"chipFamily": "ESP32"`.
  Devices never matched that build: the `update` entity sat on *unknown* in
  Home Assistant, with only a misleading `Failed to parse JSON from …` on the
  device. An unrecognised chip id now fails the publish (naming the id in the
  log) instead of guessing a wrong-but-plausible value.
- **Manual publish reads the chip family out of the firmware.** The dropdown
  defaults to *Auto* and is only needed for targets whose header carries no
  chip id (ESP8266/RP2040); when the header does carry one it overrides a
  hand-picked value, so a C3 binary can no longer be published as `ESP32`.

## 0.4.0

- Generated ESPHome packages are now a single `ota.yaml`: Update entity and
  force-install button share one `ota:` / `http_request:` block, so they can
  be used together. The button keeps the randomized `?r=` cache buster from
  0.3.5. `update.yaml` and `flash_button.yaml` are still written as identical
  copies, so existing `!include`s keep working.

## 0.3.7

- Renamed the display name from "ESPHome OTA Server" to **"ESPHome OTA
  Publisher"** — this add-on doesn't itself serve OTA traffic to devices
  (Home Assistant's own `/local` static file server does that); it builds
  or accepts firmware and publishes it there. `slug: esphome_ota` and the
  repo/folder path are unchanged, so this is not a reinstall for existing
  users — just the name shown in the Supervisor UI, panel, page title, and
  docs.

## 0.3.6

- `flash_button.yaml` is now labeled "A" (recommended default) and
  `update.yaml` "B", matching the reordered docs. The generated
  `flash_button.yaml` now documents its button's id (`ota_flash_button`)
  inline and in the header, with a copy-paste example of triggering the same
  flash from a different button (e.g. a physical GPIO button) via
  `button.press: ota_flash_button` instead of duplicating the
  `ota.http_request.flash` call.
- The **per-device YAML snippet shown in the Ingress UI** (not just the
  generated package file) now carries the same `ota_flash_button` /
  `button.press` example for option A, plus a commented-out
  `http_request: verify_ssl: false` note for memory-constrained boards
  (typically ESP8266) on both options.
- The Ingress UI's YAML snippets each get a **copy-to-clipboard button**
  next to their label, instead of select-all-by-hand. Falls back to the
  legacy `execCommand('copy')` when `navigator.clipboard` isn't available
  (Ingress is often plain HTTP on the LAN, which isn't a secure context).
- DOCS.md's package sections got the same treatment as the generated
  files: option A now shows the `button.press` GPIO example, and option
  B's `update.check`/`on_update_available`/`update.perform` example is a
  real YAML code block instead of a cramped inline-bracket description.

## 0.3.5

- `flash_button.yaml`'s `url`/`md5_url` are now lambdas that append a random
  `?r=<random_uint32()>` on every press, instead of a fixed URL. Diagnosed
  against a real report: a Cloudflare tunnel was caching `.ota.bin` at the
  edge (`cf-cache-status: HIT`, hours-old) while `.ota.bin.md5` stayed
  uncached and current, so the device kept downloading stale firmware
  against a fresh digest and aborting with an MD5 mismatch. The random query
  string makes every press a cache miss by construction, so this can't
  happen regardless of what's sitting in front of Home Assistant. Devices
  need one recompile + reflash (by any method that still works) to pick up
  the new package.

## 0.3.4

- Fixed the sidebar panel icon not rendering: `mdi:home-upload-outline` (set
  in 0.3.1) isn't a real Material Design Icons name, so the sidebar showed no
  icon at all. Switched to `mdi:upload-network-outline`, which exists.
- Fixed `logo.png`'s "ESPHome" text being invisible in dark theme: the 0.3.1
  refresh drew it as black text on a transparent background, which blends
  into HA's dark add-on panels. The logo now sits on its own solid `#18BCF2`
  rounded background with white text/icon, matching this repo's other
  add-ons, so it's legible in both themes.

## 0.3.3

- Generated packages (`update.yaml` / `flash_button.yaml`) now use
  `http_request: timeout: 60s` instead of `15s`, so remote/tunnel OTA
  downloads of ~1–2 MB firmware are less likely to abort mid-transfer.

## 0.3.2

- Manual device rows now have an **Upload** button that reopens the Manual
  publish form pre-filled with that node's name / chip / version / title, so
  you can replace the firmware without deleting first.
- Fixed the device table's stepped row borders: `.actions` used `display:flex`
  directly on the `<td>`, which drops table-cell layout. Buttons live in an
  inner flex div now, and name/version cells always reserve a subtitle line
  so row heights stay even.

## 0.3.1

- Refreshed add-on **icon** / **logo** to the current ESPHome house mark
  (Open Home Foundation branding, `#18BCF2`) with an OTA upload badge, and
  switched the sidebar `panel_icon` from `mdi:chip` to
  `mdi:home-upload-outline`.
- **Manually published devices now show up in the device table**, marked
  with a "manual" badge, instead of only existing as a one-off success
  message. `GET /api/devices` merges the ESPHome dashboard's list with
  `Publisher.list_published()` — a scan of what's actually on disk, so
  there's no separate tracking state to drift out of sync with reality.
- **`GET /api/devices` no longer 502s when the ESPHome dashboard is
  unreachable.** That used to blank the whole table — including manually
  published devices that never needed the dashboard in the first place. It
  now renders whatever it has (manual rows still work) with a banner
  explaining the dashboard is unreachable, instead of an all-or-nothing
  failure.
- Delete button added per published row (`DELETE /api/publish/{node}` was
  already there; nothing in the UI called it until now).
- Both generated packages now set an explicit `id:` on their entity
  (`ota_update` / `ota_flash_button`), so the device's own YAML can
  reference it (e.g. from a lambda or an automation) without redeclaring it.
- Build/compile output no longer carries raw ANSI escape codes (`\x1b[32m`,
  `\x1b[K`, …) into the job log — GCC/ninja/ESPHome's own logger all colorize
  output for a real terminal, which this add-on isn't, so they showed up as
  literal `[32m` / `[K` noise. Stripped in `Job.log()`.
- The firmware download after a build now has an explicit timeout (180s,
  was unbounded beyond aiohttp's default) and logs its own progress
  checkpoints, and `firmware/follow_job` streaming now polls in 20s slices
  with a synthetic heartbeat during quiet compile phases — a build that's
  genuinely still running (a slow, quiet `idf.py` step) now shows something
  in the job log instead of looking indistinguishable from a stuck job.
- Fixed a UI row-height inconsistency: the Status column's "no
  project.version" hint was a second visible line only on some rows, making
  row heights (and therefore the shared row border) uneven from row to row.
  It's a tooltip now, not a second line.

## 0.3.0

**`base_url` no longer defaults to the host's LAN address.** This add-on
exists for devices ESPHome's own local/mDNS OTA can't reach — i.e. devices
outside the LAN — so a LAN IP was the wrong default for its actual use case
(confirmed against a real report: a remote device's generated `source:` URL
pointed at `192.168.x.x`, unreachable from where the device actually is).
Resolution order is now: the `base_url` option, if set → Home Assistant's
configured external URL (`GET /core/api/config`, needs the new
`homeassistant_api: true` permission) → the LAN address as a last resort,
now logged as a loud warning explaining it won't work off-LAN instead of
silently becoming the default.

**Manual publish**, for anyone who'd rather not open ESPHome's public port at
all: a form in the add-on's Ingress panel (node name, chip family, version,
`firmware.ota.bin`) that publishes a file you downloaded from the ESPHome
dashboard yourself, with no WebSocket connection to ESPHome involved.
`POST /api/publish/manual`.

**`ota_base_url` substitution** in both generated packages, defaulting to the
add-on's `base_url` but overridable per-device (ESPHome's own config
overrides same-named package substitutions) — for a device that needs a
different address than the rest of the fleet.

**Build & publish button now gives immediate feedback.** Clicking it used to
show nothing until the POST request resolved, which could be several seconds
behind a slow dashboard connection or a queued build — indistinguishable from
the click not registering. All build/publish controls now disable
synchronously on click, before any network call.

## 0.2.1

- Still-unreachable dashboard is now diagnosable: `find_dashboard_url` logs
  the raw `network` map the Supervisor returned for each candidate ESPHome
  add-on at info level, so "port not mapped yet" and "mapped, but this add-on
  isn't recognizing it" no longer look identical in the log.

## 0.2.0

Fixes the `GET /api/devices` 502 seen in the field: `Cannot reach the ESPHome
dashboard ... 403, message='Invalid response status'`.

- Root cause: the ESPHome dashboard's ingress site is guarded by
  `ingress_peer_guard` middleware that only admits loopback and the
  Supervisor container's own fixed address — not sibling add-ons, no matter
  which address or port they dial. The `172.30.32.1` gateway theory this
  add-on was built on doesn't hold; that address reaches device-builder's
  listener, but the listener then 403s anything that isn't Supervisor or
  loopback.
- The only other door in is ESPHome's public port, and device-builder only
  binds it when the **ESPHome** add-on has both a mapped `6052/tcp` port and
  `leave_front_door_open` turned on. `supervisor.py` no longer tries the
  ingress port at all — it looks for the mapped public port and reports
  clearly (in the add-on log) when it isn't there yet.
- This does mean the ESPHome dashboard — configs, `secrets.yaml`,
  rebuild/reflash — becomes unauthenticated on the LAN as a prerequisite.
  Confirmed with the maintainer as an acceptable trade-off for a LAN already
  treated as trusted (HA itself runs internal `http`, and this add-on's own
  `/local` firmware files are unauthenticated by the same design). Documented
  up front in README/DOCS rather than left as a troubleshooting footnote.
- A 403 specifically now raises a message naming the actual fix instead of a
  generic "cannot reach" — see `dashboard.py`'s `WSServerHandshakeError`
  handling.

## 0.1.1

- `GET /api/devices` now logs the real `DashboardError` on failure instead of
  only returning it in the HTTP response, so a 502 is diagnosable from the
  add-on log.
- Fixed a bug where a WebSocket send failure was fired-and-forgotten: any
  connection drop while sending a command surfaced as a silent 60s timeout
  with no explanation. It now raises immediately with the underlying error.
- `devices/list` response parsing logs the raw shape at debug level when it
  doesn't match the expected `{"configured": [...]}` field, instead of
  quietly returning an empty list.
- The Ingress UI is now in English by default, auto-switching to Korean when
  the browser's language is Korean (with a manual override). It was
  previously hardcoded to Korean.

## 0.1.0

Initial release.

- Pulls `firmware.ota.bin` from the ESPHome Device Builder add-on over its
  documented WebSocket API (`firmware/compile`, `firmware/follow_job`,
  `firmware/download_token`), auto-detected via the Supervisor.
- Publishes firmware, MD5, and an ESP-Web-Tools manifest to `<config>/www/`,
  served by Home Assistant at `/local/` — no host ports opened.
- Generates two ESPHome packages: `update.yaml` (update entity) and
  `flash_button.yaml` (force-install button).
- Relative manifest paths so LAN and remote-tunnel access both work unchanged;
  `?v=<md5>` cache buster against proxy caching of `/local`.
- Ingress UI to build, publish, and copy the per-device YAML snippet.
