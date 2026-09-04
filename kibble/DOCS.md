# Kibble

Self-hosted pet care journal as a Home Assistant app — one-tap event presets, medication
courses and reminders, photo attachments, and a token API for automations.

## How to use

1. Start the app.
2. Open the **Kibble** entry in the sidebar, or go to `http://<ha-ip>:3083`.
3. Create the first admin account, run through onboarding to add your pets, then log care
   events from the home screen.

Data persists under `/data` — Postgres in `/data/postgres`, pet photos and event
attachments in `/data/uploads`, generated secrets in `/data/secrets`.

## Ingress and the host port

Both work. The sidebar entry goes through Home Assistant's Ingress, which is also what
makes the app reachable from your Home Assistant external URL — the host port is only
reachable on the LAN unless you expose it yourself.

Ingress serves the app under `/api/hassio_ingress/<token>/`, and that token is handed out
per installation. Upstream builds the web image with a placeholder base path and rewrites
it at start-up, so this app looks its Ingress entry up from the Supervisor and passes it
in. If that lookup fails the app still starts and serves on the host port; the log says so
and the sidebar entry will not render.

The media cookie is issued without the `Secure` flag, since a Secure cookie would never
come back over plain http on the host port and every photo would answer 401.

Installing the PWA (**Add to Home Screen**) and Web Push reminders need a secure context,
which a browser only grants to `localhost` and `https://` — so they work through the
sidebar entry when your Home Assistant is served over https, and not over the plain-http
host port. Set `APP_PUBLIC_URL` in the app's own settings to the URL you actually reach
it at.

## Options

There are none, on purpose. Integration keys — the Kakao map key and the Web Push (VAPID)
pair, which the app can generate for you — belong in Kibble's own **/integrations**
screen. Those values are stored in its database and take priority over anything in the
environment, so configuring them twice would only create a second, silently ignored copy.

The Postgres password and JWT secret are generated on first start and kept under
`/data/secrets`.

## Backup and restore

The app's **Backup** screen packs the database export and `/data/uploads` into a
`.tar.gz` you download, and restores from the same file. That is Kibble's own backup, and
it is separate from a Home Assistant snapshot — a snapshot of this app captures `/data`
wholesale, including Postgres.

## Requirements

`amd64` only — the upstream `kibble-api` / `kibble-web` images are published for
linux/amd64 alone.
