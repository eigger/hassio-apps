# Changelog

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
