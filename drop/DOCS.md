# Drop

Self-hosted file sharing between phone and PC, as a Home Assistant app.

## How to use

1. Start the app.
2. Open the **Drop** entry in the sidebar, or go to `http://<ha-ip>:3082`.
3. Create the first admin account, then upload from the phone and pick the files up on
   the PC (or the other way round).

Data persists under `/data` — Postgres in `/data/postgres`, uploaded files in
`/data/uploads`, generated secrets in `/data/secrets`.

## Ingress and the host port

Both work. The sidebar entry goes through Home Assistant's Ingress, which is also what
makes the app reachable from your Home Assistant external URL — the host port is only
reachable on the LAN unless you expose it yourself.

Ingress serves the app under `/api/hassio_ingress/<token>/`, and that token is handed out
per installation. Upstream builds the web image with a placeholder base path and rewrites
it at start-up, so this app looks its Ingress entry up from the Supervisor and passes it
in. If that lookup fails the app still starts and serves on the host port; the log says so
and the sidebar entry will not render.

## Uploads

The API stores files under `/data/uploads` and caps one file at 10 GB, the same default
upstream's production compose file uses. Chunked uploads stage their parts in the same
directory so a finished upload is moved into place with a rename rather than a copy.

nginx sets no request body limit and does not buffer request or response bodies, so a
multi-gigabyte transfer streams straight through instead of being spooled into the
container's writable layer.

Installing the PWA (**Add to Home Screen**) and the Android Web Share Target that comes
with it need a secure context — a browser only treats `localhost` and `https://` as one.
That means the sidebar entry works for it when your Home Assistant is served over https;
the plain-http host port does not.

## Options

There are none. Drop keeps its settings in its own **Settings** screen, and the Postgres
password and JWT secret are generated on first start and kept under `/data/secrets`.

## Requirements

`amd64` only — the upstream `drop-api` / `drop-web` images are published for
linux/amd64 alone.
