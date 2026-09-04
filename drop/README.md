# Drop (Home Assistant App)

Runs [drop](https://github.com/eigger/drop) **all-in-one** (Postgres + API + Web), with nginx routing like the upstream Caddyfile.

## Install

1. **Settings → Apps → ⋮ → Repositories** → add this repo
2. Install **Drop**, start it
3. Open it from the **Drop** sidebar entry (Ingress), or on the host port at
   **http://&lt;home-assistant-ip&gt;:3082**

First launch: create an admin on the login screen — that path is only open while the
user table is empty.

JWT/DB secrets are auto-generated under `/data`.

## Ingress

Ingress is the only way in from Home Assistant's own external URL, so the sidebar entry
works from outside your LAN while the host port does not.

Serving it took an upstream change: `next build` bakes the base path into the output, but
HA hands out `/api/hassio_ingress/<token>/` per installation, so the path is only known at
start-up. Upstream 0.5.0 builds the image with a placeholder and rewrites it when the
container starts; this app resolves its Ingress entry from the Supervisor and passes it in.

The host port stays published, so both doors work at once. Ingress arrives with the prefix
stripped, while a browser on the host port asks for the prefixed URLs the page carries —
nginx folds the two into one shape and puts the prefix back on for the web app.

Default host port is **3082** (Stash **3080**, Garage **3081**, Kibble **3083**).

## Uploads

Files, thumbnails and in-flight chunks live under `/data/uploads`, so they survive an
app update. The API caps a single file at **10 GB** (upstream's production default);
nginx sets no limit of its own and streams the body straight through, so the cap is
enforced in one place and a long upload is never buffered to the container filesystem
first.

The Web Share Target — sharing straight from the Android share sheet — needs the PWA to
be installed, and a browser only offers that in a secure context (`https://` or
`localhost`). Through Ingress you already have one if your Home Assistant is on https;
over plain http on the host port you do not.

Upstream images: `ghcr.io/eigger/drop-api:0.5.0`, `ghcr.io/eigger/drop-web:0.5.0`

Nothing is built from source here — the app copies the upstream release images in and
runs them next to Postgres and nginx, so the app version tracks the upstream version.
A scheduled workflow ([upstream-bump.yml](../.github/workflows/upstream-bump.yml)) opens
a PR whenever upstream — or the add-on base image — publishes a newer tag.

## Options

None. Everything Drop can be configured with lives in its own **Settings** screen, and
the Postgres password and JWT secret are generated on first start under `/data/secrets`.

## Architecture

`amd64` only — upstream publishes no arm64 image, so the app cannot be built for
Raspberry Pi or other aarch64 hosts.
