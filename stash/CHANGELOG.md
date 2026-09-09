# Changelog

## 0.8.1

- Follow upstream to `stash-api`/`stash-web` **0.8.1** ([release notes](https://github.com/eigger/stash/releases/tag/v0.8.1))

## 0.7.5.1

- Base image `21.0.3` → **`21.0.4`**

## 0.7.5

- **App re-enabled**:
  - The folder was dot-prefixed (`.stash`) so the Supervisor stopped offering it; it is discoverable again.
  - Existing installs are unaffected — the slug, host port, and `/data` layout are unchanged.
- **Upstream images 0.3.1 → 0.7.5**:
  - Pins `ghcr.io/eigger/stash-api:0.7.5` and `ghcr.io/eigger/stash-web:0.7.5`.
  - Prisma migrations pass `--config apps/api/prisma.config.ts` when the image ships it, which upstream now requires.
  - Installs `libstdc++`/`libgcc`: the API image is built on `node:24-alpine` and the Node binary copied out of it will not start without them.
  - Dropped the `openssl` package — it is the only one that has to match the base image's pinned `libcrypto3`/`libssl3` exactly, and it broke the build. Secrets now come from `/dev/urandom` via busybox `od`.
- **Ingress**:
  - The app has a sidebar entry and is reachable through Home Assistant's own external URL. The host port only ever worked on the LAN.
  - Upstream 0.7.5 builds the web image with a placeholder base path and rewrites it at start-up; this app resolves its Ingress entry from the Supervisor and passes it in.
  - nginx folds both front doors into one shape: Ingress arrives with the prefix stripped, a browser on the host port asks for the prefixed URLs the page carries.
  - The host port (3080) stays published. If the Supervisor lookup fails, the app still starts on the host port and logs why.
- **`aarch64` dropped**: upstream only publishes linux/amd64 images, so the arm build could never have succeeded.
- No `build.yaml`: the Supervisor deprecated it, and its values are the `ARG` defaults in the Dockerfile.

## 0.3.1.1

- Drop Ingress; expose host port 3080 with Open Web UI
- Keep upstream images pinned to 0.3.1

## 0.3.1

- Initial all-in-one app packaging
