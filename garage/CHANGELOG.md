# Changelog

## 1.3.9.1

- Base image `21.0.3` → **`21.0.4`**

## 1.3.9

- Follow upstream to `garage-api`/`garage-web` **1.3.9** ([release notes](https://github.com/eigger/garage/releases/tag/v1.3.9))
  - Fixes the offline shell cache, which had been failing silently since 1.3.8: `trailingSlash` turned the service worker's `/login` entry into a redirect, and `cache.addAll` drops the whole list when one entry is redirected.

## 1.3.8

- **Fix the 404 after logging in through Ingress**: Home Assistant registers exactly one ingress route, `/api/hassio_ingress/{token}/{path:.*}`, so the trailing slash is required — while Next normalised the base path root to the slash-less form. `router.push("/")` therefore produced a URL outside the route and Home Assistant answered 404 before the request ever reached the app, which is why only the login screen worked.
- Fixed upstream in 1.3.8 with `trailingSlash: true`, plus two client paths that bypassed the base path (the post-restore jump to `/login`, and the Hyundai OAuth redirect URI).
- **Reverted the nginx root workaround** added in 1.3.7.2: it only covered the server half of the same mismatch, and with upstream fixed the plain path is right again.

## 1.3.7.2

- **Fix the Ingress panel showing 404**: the web app answers at its base path *without* a trailing slash, so proxying the root request to `<base>/` earned a `308` to `<base>` — a redirect that leaves Home Assistant's ingress route and 404s. nginx now proxies the prefix alone for the root request; every other path is unchanged.

## 1.3.7.1

- **Dropped `build.yaml`**: the Supervisor now warns that it is deprecated. Its two settings — the base image and the upstream image tags — were already the `ARG` defaults in the Dockerfile, and with no build config the Supervisor stops passing `BUILD_FROM` and leaves those defaults alone. Nothing about the built image changes.

## 1.3.7

- **Ingress**:
  - The app now has a sidebar entry and is reachable through Home Assistant's own external URL — the host port only ever worked on the LAN.
  - Needed an upstream change (eigger/garage#84, released in 1.3.7): `next build` bakes the base path in, but HA assigns `/api/hassio_ingress/<token>/` per installation. Upstream now builds with a placeholder and rewrites it at start-up; this app resolves its Ingress entry from the Supervisor and passes it in.
  - nginx folds both front doors into one shape: Ingress arrives with the prefix stripped, a browser on the host port asks for the prefixed URLs the page carries.
  - The host port (default 3081) stays published, so nothing that worked before stops working. The **Open Web UI** button is gone: it resolved to `<host>:3081`, which is what failed from outside the LAN — open the sidebar entry, or type the host-port URL. If the Supervisor lookup fails, the app still starts on the host port and logs why.
- **Upstream images 1.3.6 → 1.3.7**

## 1.3.6.1

- **Fix the build failing on `apk add openssl`**:
  - Base image `21.0.0` → **`21.0.3`**: it pinned `libcrypto3`/`libssl3` at `3.5.7-r0`, three releases behind the Alpine index, whose `openssl 3.5.8-r0` demands the matching `3.5.8` libraries — apk could not resolve it. `21.0.3` pins `3.5.8-r0`.
  - Dropped the `openssl` package anyway: it is the only one that has to move in exact lockstep with the base's pinned libraries, so the next security release would break the build again until the base catches up. It was used for `openssl rand -hex` alone, and secrets now come from `/dev/urandom` via busybox `od`.
  - The base image is now tracked by the bump bot too, so it cannot fall behind again unnoticed.
- **Integration options removed**:
  - Garage keeps Opinet, 천안사랑카드, EV charger and Web Push (VAPID) keys in its own **/integrations** screen, and `getSetting()` prefers the database value over the environment.
  - An add-on option would therefore be ignored the moment anything is saved in the UI — and it would have parked the VAPID private key in the add-on config as well. The app stays the single place to set them.

## 1.3.6

- **App re-enabled**:
  - The folder was dot-prefixed (`.garage`) so the Supervisor stopped offering it; it is discoverable again.
  - Existing installs are unaffected — the slug, ports, and `/data` layout are unchanged.
- **Upstream images 0.2.14 → 1.3.6**:
  - Pins `ghcr.io/eigger/garage-api:1.3.6` and `ghcr.io/eigger/garage-web:1.3.6` in both the Dockerfile and `build.yaml`.
  - Prisma migrations now pass `--config apps/api/prisma.config.ts`, which upstream 1.x requires; the flag is only added when the image actually ships that file, so an older pin keeps working.
  - Installs `libstdc++`/`libgcc`: the API image moved to `node:22-alpine` and the Node binary copied out of it will not start without them.
- **`aarch64` dropped**:
  - Upstream publishes `garage-api` / `garage-web` for **linux/amd64 only** — the arm build could never have succeeded.
  - Home Assistant on Raspberry Pi and other arm hosts can no longer install this app.
- **Optional integrations exposed as options**:
  - `opinet_api_key` (`OPINET_API_KEY`) — real nearby fuel prices instead of mock data.
  - `cheonan_card_enabled` (`CHEONAN_CARD_ENABLED`) — 천안사랑카드 stations; needs the Opinet key too.
  - `ev_charger_api_key` (`EV_CHARGER_API_KEY`) — 한국환경공단 EV charger data (data.go.kr).
  - `vapid_public_key` / `vapid_private_key` / `vapid_subject` (`VAPID_*`) — Web Push reminders.
  - All empty by default, matching the env vars upstream's `docker-compose.prod.yml` passes; the app runs without any of them.
- **Housekeeping**:
  - Dropped `startup: application` and `boot: auto` from the config — both are the Home Assistant defaults, so behaviour is unchanged.
  - Upstream releases are now tracked by `.github/workflows/upstream-bump.yml`, which opens a PR when a newer tag is published.

## 0.2.14.1

- Drop Ingress; expose host port 3081 with Open Web UI (fixes blank Next.js page)
- Keep upstream images pinned to 0.2.14

## 0.2.14

- Initial all-in-one app packaging
