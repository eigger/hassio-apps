# Garage (Home Assistant App)

Runs [garage](https://github.com/eigger/garage) **all-in-one** (Postgres + API + Web), with nginx routing like the upstream Caddyfile.

## Install

1. **Settings → Apps → ⋮ → Repositories** → add this repo
2. Install **Garage**, start it
3. Open it from the **Garage** sidebar entry (Ingress), or on the host port at
   **http://&lt;home-assistant-ip&gt;:3081**

First launch: create an admin on `/login`.

API keys are configured in the Garage web UI. JWT/DB secrets are auto-generated under `/data`.

## Ingress

Ingress is the only way in from Home Assistant's own external URL, so the sidebar entry
works from outside your LAN while the host port does not.

Serving it took an upstream change ([eigger/garage#84](https://github.com/eigger/garage/issues/84)):
`next build` bakes the base path into the output, but HA hands out
`/api/hassio_ingress/<token>/` per installation, so the path is only known at start-up.
Upstream 1.3.7 builds the image with a placeholder and rewrites it when the container
starts; this app resolves its Ingress entry from the Supervisor and passes it in.

The host port stays published, so both doors work at once. Ingress arrives with the
prefix stripped, while a browser on the host port asks for the prefixed URLs the page
carries — nginx folds the two into one shape and puts the prefix back on for the web app.

There is no **Open Web UI** button any more: it resolved to `<host>:3081`, which is
precisely what does not work from outside. Default host port is still **3081** so it does
not collide with Stash (**3080**) — reach it by typing the URL.

Upstream images: `ghcr.io/eigger/garage-api:1.5.0`, `ghcr.io/eigger/garage-web:1.5.0`

Nothing is built from source here — the app copies the upstream release images in and
runs them next to Postgres and nginx, so the app version tracks the upstream version.
A scheduled workflow ([upstream-bump.yml](../.github/workflows/upstream-bump.yml)) opens
a PR whenever upstream — or the add-on base image — publishes a newer tag.

## Options

None. Garage manages its integration keys itself — Opinet, 천안사랑카드, the EV
charger API and Web Push (VAPID, generated with a button) all live in the app's
**/integrations** screen. The API resolves them through `getSetting()`, which
prefers the value in its own database and only falls back to the environment, so
an add-on option would be ignored as soon as anything is saved in the UI.

## Architecture

`amd64` only — upstream publishes no arm64 image, so the app cannot be built for
Raspberry Pi or other aarch64 hosts.
