# Changelog

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
