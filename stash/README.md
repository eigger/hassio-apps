# Stash (Home Assistant App)

Runs [stash](https://github.com/eigger/stash) **all-in-one** (Postgres + API + Web), with nginx routing like the upstream Caddyfile.

## Install

1. **Settings → Apps → ⋮ → Repositories** → add this repo
2. Install **Stash**, start it
3. Open it from the **Stash** sidebar entry (Ingress), or on the host port at
   **http://&lt;home-assistant-ip&gt;:3080**

First launch: create an admin on the login screen.

JWT/DB secrets are auto-generated under `/data`.

## Ingress

Ingress is the only way in from Home Assistant's own external URL, so the sidebar entry
works from outside your LAN while the host port does not.

Serving it took an upstream change: `next build` bakes the base path into the output, but
HA hands out `/api/hassio_ingress/<token>/` per installation, so the path is only known at
start-up. Upstream 0.7.5 builds the image with a placeholder and rewrites it when the
container starts; this app resolves its Ingress entry from the Supervisor and passes it in.

The host port stays published, so both doors work at once. Ingress arrives with the prefix
stripped, while a browser on the host port asks for the prefixed URLs the page carries —
nginx folds the two into one shape and puts the prefix back on for the web app.

Default host port is **3080** (Garage uses **3081**).

Upstream images: `ghcr.io/eigger/stash-api:0.8.1`, `ghcr.io/eigger/stash-web:0.8.1`

Nothing is built from source here — the app copies the upstream release images in and
runs them next to Postgres and nginx, so the app version tracks the upstream version.
A scheduled workflow ([upstream-bump.yml](../.github/workflows/upstream-bump.yml)) opens
a PR whenever upstream — or the add-on base image — publishes a newer tag.

## Architecture

`amd64` only — upstream publishes no arm64 image, so the app cannot be built for
Raspberry Pi or other aarch64 hosts.
