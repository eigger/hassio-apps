# Changelog

## 0.5.0.1

- **Fix Prisma migrations crashing on start**: Prisma 5 on Alpine only looks for
  `libssl.so` in `/lib`. The HA base keeps OpenSSL 3 under `/usr/lib`, so detection
  failed, the CLI defaulted to `openssl-1.1.x`, and `migrate deploy` died parsing
  `Error loading shared library libssl.so.1.1`. The libraries were already in the
  image; they are now linked into `/lib` where Prisma 5 can see them. Stash, Garage
  and Kibble do not need this — they run Prisma 7, which searches `/usr/lib` itself.
  `apk add openssl` is still avoided: it has to match the base's pinned `libcrypto3`
  / `libssl3` exactly, and that is what broke the Garage build.

## 0.5.0

- Initial all-in-one app packaging, modelled on Stash and Garage: one container running
  Postgres, the upstream API and web images, and nginx routing `/api` + `/health` to the
  API and everything else to the web app, exactly as upstream's Caddyfile does.
- Pins `ghcr.io/eigger/drop-api:0.5.0` and `ghcr.io/eigger/drop-web:0.5.0`.
- **Ingress**:
  - The app has a sidebar entry and is reachable through Home Assistant's own external
    URL. The host port only ever works on the LAN.
  - Needed an upstream change, released in 0.5.0: `next build` bakes the base path into
    the output, but HA assigns `/api/hassio_ingress/<token>/` per installation. Upstream
    now builds the web image with a placeholder and rewrites it at start-up; this app
    resolves its Ingress entry from the Supervisor and passes it in.
  - nginx folds both front doors into one shape: Ingress arrives with the prefix stripped,
    a browser on the host port asks for the prefixed URLs the page carries.
  - The host port (3082) stays published, next to Stash (3080), Garage (3081) and
    Kibble (3083). If the Supervisor lookup fails, the app still starts on the host port
    and logs why.
- **`UPLOAD_DIR=/data/uploads`**: upstream defaults it to `<cwd>/uploads`, which inside
  the image is `/opt/app/api/uploads` — files there would be thrown away on every update.
  Thumbnails and chunk staging hang off the same directory, so a completed chunked upload
  is still a rename rather than a cross-filesystem copy.
- **nginx does not police uploads**: `client_max_body_size 0`, with request and response
  buffering off. The API already knows the cap (`FILE_SIZE_LIMIT_MB`, 10 GB by default),
  and buffering a multi-gigabyte body would fill the container's writable layer before
  the API saw a byte.
- `amd64` only — upstream publishes `drop-api` / `drop-web` for linux/amd64 alone.
- Secrets come from `/dev/urandom` via busybox `od`, not `openssl`: the base image pins
  `libcrypto3`/`libssl3` to an exact version, so `apk add openssl` breaks whenever the
  Alpine index moves ahead of it.
- No `build.yaml`: the Supervisor deprecated it, and its values are the `ARG` defaults in
  the Dockerfile.
- Tracked by the bump bot and the config linter alongside the other apps.
