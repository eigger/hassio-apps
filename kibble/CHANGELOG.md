# Changelog

## 0.17.3

- Follow upstream to `kibble-api`/`kibble-web` **0.17.3** ([release notes](https://github.com/eigger/kibble/releases/tag/v0.17.3))

## 0.12.2

- Follow upstream to `kibble-api`/`kibble-web` **0.12.2** ([release notes](https://github.com/eigger/kibble/releases/tag/v0.12.2))

## 0.8.0

- Initial all-in-one app packaging, modelled on Stash and Garage: one container running
  Postgres, the upstream API and web images, and nginx routing `/api` + `/health` to the
  API and everything else to the web app, exactly as upstream's Caddyfile does — security
  headers included.
- Pins `ghcr.io/eigger/kibble-api:0.8.0` and `ghcr.io/eigger/kibble-web:0.8.0`.
- **Ingress**:
  - The app has a sidebar entry and is reachable through Home Assistant's own external
    URL. The host port only ever works on the LAN.
  - Needed an upstream change, released in 0.8.0: `next build` bakes the base path into
    the output, but HA assigns `/api/hassio_ingress/<token>/` per installation. Upstream
    now builds the web image with a placeholder and rewrites it at start-up; this app
    resolves its Ingress entry from the Supervisor and passes it in.
  - nginx folds both front doors into one shape: Ingress arrives with the prefix stripped,
    a browser on the host port asks for the prefixed URLs the page carries.
  - The host port (3083) stays published, next to Stash (3080), Garage (3081) and
    Drop (3082). If the Supervisor lookup fails, the app still starts on the host port
    and logs why.
  - Upstream's `X-Frame-Options: DENY` is the one Caddyfile header not carried over —
    Ingress renders the app in a Home Assistant iframe, and DENY would blank the panel.
    The rest (`nosniff`, `Referrer-Policy`, `Permissions-Policy`) are kept.
- **`UPLOAD_DIR=/data/uploads`**: upstream defaults it to `<cwd>/uploads`, which inside
  the image is `/opt/app/api/uploads` — pet photos and attachments there would be thrown
  away on every update. Chunk staging and backup archives hang off the same directory.
- **`COOKIE_SECURE=false`**: the host port is plain http, and a Secure media cookie would
  never be sent back, so every photo would answer 401.
- **No `prisma db seed`**: the seed CLI resolves its script relative to `/app` and imports
  `apps/api/src`, which the release image does not ship. The system event types it would
  create are seeded by the API itself on start-up, so the step is redundant — the same
  reason upstream's production compose file dropped it.
- **No options**: Kibble stores the Kakao map key and the VAPID pair in its own database
  through `getSetting()`, which prefers the database value over the environment, so an
  add-on option would be ignored the moment anything is saved in the UI. Garage's
  reasoning, applied here.
- Adds the `tar` package: the backup and restore screen shells out to `tar` to build and
  unpack its archive.
- `amd64` only — upstream publishes `kibble-api` / `kibble-web` for linux/amd64 alone.
- Secrets come from `/dev/urandom` via busybox `od`, not `openssl`: the base image pins
  `libcrypto3`/`libssl3` to an exact version, so `apk add openssl` breaks whenever the
  Alpine index moves ahead of it. The API refuses to start in production on an empty or
  placeholder `JWT_SECRET`, so the generated one matters.
- No `build.yaml`: the Supervisor deprecated it, and its values are the `ARG` defaults in
  the Dockerfile.
- Tracked by the bump bot and the config linter alongside the other apps.
