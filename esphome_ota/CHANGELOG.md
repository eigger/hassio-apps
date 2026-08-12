# Changelog

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
