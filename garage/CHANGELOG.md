# Changelog

## 1.3.6

- Re-enable the app (the folder was dot-prefixed and hidden from the Supervisor)
- Follow upstream to `garage-api`/`garage-web` **1.3.6** (was 0.2.14)
- Drop `aarch64`: upstream only publishes linux/amd64 images
- Pass Prisma's `--config apps/api/prisma.config.ts` when the image ships it (required since upstream 1.x)
- Add options for the optional upstream integrations: Opinet, 천안사랑카드, EV charger API, Web Push (VAPID)
- Install `libstdc++`/`libgcc` so the Node runtime copied from `node:22-alpine` can start

## 0.2.14.1

- Drop Ingress; expose host port 3081 with Open Web UI (fixes blank Next.js page)
- Keep upstream images pinned to 0.2.14

## 0.2.14

- Initial all-in-one app packaging
