# Kibble (Home Assistant App)

Runs [kibble](https://github.com/eigger/kibble) **all-in-one** (Postgres + API + Web), with nginx routing like the upstream Caddyfile.

## Install

1. **Settings → Apps → ⋮ → Repositories** → add this repo
2. Install **Kibble**, start it
3. Open it from the **Kibble** sidebar entry (Ingress), or on the host port at
   **http://&lt;home-assistant-ip&gt;:3083**

First launch: create an admin on the login screen — that path is only open while no
account exists.

Integration keys are configured in the Kibble web UI. JWT/DB secrets are auto-generated
under `/data`.

## Ingress

Ingress is the only way in from Home Assistant's own external URL, so the sidebar entry
works from outside your LAN while the host port does not.

Serving it took an upstream change: `next build` bakes the base path into the output, but
HA hands out `/api/hassio_ingress/<token>/` per installation, so the path is only known at
start-up. Upstream 0.8.0 builds the image with a placeholder and rewrites it when the
container starts; this app resolves its Ingress entry from the Supervisor and passes it in.

The host port stays published, so both doors work at once. Ingress arrives with the prefix
stripped, while a browser on the host port asks for the prefixed URLs the page carries —
nginx folds the two into one shape and puts the prefix back on for the web app.

Default host port is **3083** (Stash **3080**, Garage **3081**, Drop **3082**).

Upstream images: `ghcr.io/eigger/kibble-api:0.21.2`, `ghcr.io/eigger/kibble-web:0.21.2`

Nothing is built from source here — the app copies the upstream release images in and
runs them next to Postgres and nginx, so the app version tracks the upstream version.
A scheduled workflow ([upstream-bump.yml](../.github/workflows/upstream-bump.yml)) opens
a PR whenever upstream — or the add-on base image — publishes a newer tag.

## Options

None. Kibble manages its own keys — the Kakao map key and the Web Push (VAPID) pair,
which the app can generate for you — in its **/integrations** screen. The API resolves
them through `getSetting()`, which prefers the value in its own database and only falls
back to the environment, so an add-on option would be ignored as soon as anything is
saved in the UI. Same reasoning as Garage.

## Architecture

`amd64` only — upstream publishes no arm64 image, so the app cannot be built for
Raspberry Pi or other aarch64 hosts.
