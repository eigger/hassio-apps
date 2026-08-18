"""Ingress web app: list devices, build, publish."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web

import metadata
import packages
import registry
import supervisor
from dashboard import DashboardClient, DashboardError
from publisher import Publisher

LOG = logging.getLogger("server")
HERE = Path(__file__).parent

# GCC/ninja/esphome's own logger all colorize their output with real ANSI CSI
# sequences (ESC '[' ... final-byte) when captured non-interactively — this
# add-on doesn't run a terminal emulator, so they'd otherwise show up as
# literal "[32m" / "[K" noise in the job log instead of being invisible.
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name, "").strip()
    return default if value in ("", "null") else value


@dataclass
class Settings:
    dashboard_url: str = field(default_factory=lambda: _env("DASHBOARD_URL"))
    dashboard_token: str = field(default_factory=lambda: _env("DASHBOARD_TOKEN"))
    publish_dir: str = field(default_factory=lambda: _env("PUBLISH_DIR", "esphome_ota"))
    base_url: str = field(default_factory=lambda: _env("BASE_URL"))
    esphome_config_dir: Path = Path("/homeassistant/esphome")
    www_root: Path = Path("/homeassistant/www")


class Job:
    """A build/publish run, followed by the UI while it streams output."""

    def __init__(self, node: str, action: str) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.node = node
        self.action = action
        self.status = "running"
        self.lines: list[str] = []
        self.error: str | None = None

    def log(self, line: str) -> None:
        self.lines.append(_ANSI_RE.sub("", line))
        # Keep the tail bounded; a full ESP-IDF build is thousands of lines.
        if len(self.lines) > 400:
            del self.lines[:-400]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "node": self.node,
            "action": self.action,
            "status": self.status,
            "error": self.error,
            "lines": self.lines[-120:],
        }


class App:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.publisher = Publisher(self.settings.www_root, self.settings.publish_dir)
        self.resolved_dashboard: str = ""
        self.resolved_base_url: str = ""
        self.base_url_source: str = ""
        self.restart_required = False
        self.jobs: dict[str, Job] = {}
        self.lock = asyncio.Lock()
        self.esphome_version: str = ""
        self.addon_version: str = ""
        self.registered: dict[str, dict[str, Any]] = {}
        self.auto_deactivate_task: asyncio.Task | None = None
        self.session: aiohttp.ClientSession | None = None

    # -- startup -----------------------------------------------------------

    async def startup(self, _: web.Application) -> None:
        self.restart_required = self.publisher.ensure_dirs()
        self.session = aiohttp.ClientSession()

        self.addon_version = await supervisor.find_self_version(self.session) or ""
        if self.settings.dashboard_url:
            self.resolved_dashboard = self.settings.dashboard_url.rstrip("/")
        else:
            self.resolved_dashboard = await supervisor.find_dashboard_url(self.session) or ""

        # This add-on exists for devices ESPHome's own local/mDNS OTA can't
        # reach — i.e. devices outside the LAN. The address that matters is
        # therefore the one HA is already configured to be reached at from
        # outside (Settings -> System -> Network), not the host's LAN IP.
        # Resolution order: explicit option > HA's configured external_url
        # > LAN IP as a last resort (logged loudly — it will not work for
        # an off-LAN device, but a working LAN-only default beats none for
        # local testing).
        if self.settings.base_url:
            self.resolved_base_url = self.settings.base_url.rstrip("/")
            self.base_url_source = "configured"
        else:
            external_url = await supervisor.find_external_url(self.session)
            if external_url:
                self.resolved_base_url = external_url.rstrip("/")
                self.base_url_source = "ha_external_url"
            else:
                host_ip = await supervisor.find_host_ip(self.session)
                self.resolved_base_url = f"http://{host_ip}:8123" if host_ip else ""
                self.base_url_source = "lan_ip_fallback"

        if self.resolved_base_url:
            if self.base_url_source == "lan_ip_fallback":
                LOG.warning(
                    "Using the host's LAN address (%s) as base_url — Home Assistant has no "
                    "external URL configured (Settings -> System -> Network). This only works "
                    "for devices on the same LAN; a device this add-on is actually meant for "
                    "won't be able to reach it. Set 'base_url' in the add-on options, or "
                    "configure HA's external URL, to fix this.",
                    self.resolved_base_url,
                )
            packages.write_packages(
                self.settings.esphome_config_dir, self.resolved_base_url, self.settings.publish_dir
            )
            self.load_registry()
            self.auto_deactivate_task = asyncio.create_task(self._auto_deactivate_loop())
        else:
            LOG.error(
                "Could not determine Home Assistant's address. Set 'base_url' in the add-on "
                "options (for example https://your-tunnel-domain) so the packages can be written."
            )

    async def shutdown(self, _: web.Application) -> None:
        if self.auto_deactivate_task:
            self.auto_deactivate_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.auto_deactivate_task
        if self.session and not self.session.closed:
            await self.session.close()

    # -- dashboard ---------------------------------------------------------

    def _client(self) -> DashboardClient:
        if not self.resolved_dashboard:
            raise DashboardError(
                "No ESPHome dashboard found. Make sure the ESPHome Device Builder add-on is "
                "running, or set 'dashboard_url' in the add-on options."
            )
        return DashboardClient(self.resolved_dashboard, self.settings.dashboard_token)

    def load_registry(self) -> None:
        data = registry.load(self.settings.esphome_config_dir)
        changed = False
        published = self.publisher.list_published(data)
        for node, rec in published.items():
            if node in data:
                continue
            token = rec.get("token") or ""
            registry.upsert(
                data,
                node,
                rec.get("version") or "1.0.0",
                rec.get("title") or node,
                token=token,
            )
            changed = True
        if changed:
            registry.save(self.settings.esphome_config_dir, data)
        self.registered = data

    def save_registry(self) -> None:
        registry.save(self.settings.esphome_config_dir, self.registered)

    def register_device(self, node: str, version: str, title: str = "") -> dict[str, Any]:
        self.load_registry()
        token = None
        if node not in self.registered:
            pub = self.publisher.published(node)
            if pub and not pub.get("token"):
                token = ""
        rec = registry.upsert(self.registered, node, version, title, token=token)
        self.save_registry()
        self.write_device_wrapper(node, rec["version"])
        return rec

    def deactivate_firmware(self, node: str) -> None:
        """Deactivate firmware binary: removes .bin from /local and keeps in storage."""
        token = (self.registered.get(node) or {}).get("token") or ""
        self.publisher.deactivate_binary(node, token=token)

    def activate_firmware(self, node: str) -> None:
        """Activate firmware binary: deploys stashed .bin from storage to /local."""
        token = (self.registered.get(node) or {}).get("token") or ""
        self.publisher.activate_binary(node, token=token)
        self._schedule_auto_deactivate(node)

    def _schedule_auto_deactivate(self, node: str) -> None:
        """Schedule expiration timer when a firmware is published or activated."""
        self.load_registry()
        rec = self.registered.get(node) or {}
        ad = rec.get("auto_deactivate") or {"mode": "on_success", "timer_hours": 12}
        hours = ad.get("timer_hours", 12)
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(hours=hours)).isoformat(timespec="seconds")
        registry.set_auto_deactivate(
            self.registered,
            node,
            ad.get("mode", "on_success"),
            hours,
            expires_at=expires_at,
            last_status="Active (monitoring update)",
        )
        self.save_registry()

    def match_ha_update_entity(
        self,
        node: str,
        friendly_name: str,
        explicit_id: str | None,
        update_entities: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        if explicit_id and explicit_id in update_entities:
            return update_entities[explicit_id]

        norm_node = node.lower().replace("-", "_")
        norm_title = re.sub(r"[^a-z0-9_]", "", (friendly_name or node).lower().replace(" ", "_").replace("-", "_"))

        candidates = [
            f"update.{norm_node}",
            f"update.{norm_node}_firmware",
            f"update.{norm_node}_ota_update",
            f"update.{norm_node}_update",
            f"update.{norm_title}",
            f"update.{norm_title}_firmware",
            f"update.{norm_title}_ota_update",
            f"update.{norm_title}_update",
        ]
        for cand in candidates:
            if cand in update_entities:
                return update_entities[cand]

        for eid, entity in update_entities.items():
            title = (entity.get("title") or entity.get("friendly_name") or "").strip().lower()
            if friendly_name and title == friendly_name.strip().lower():
                return entity
        return None

    async def _auto_deactivate_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(30)
                await self._check_auto_deactivate()
            except asyncio.CancelledError:
                break
            except Exception as err:
                LOG.debug("Error in auto_deactivate_loop: %s", err)

    async def _check_auto_deactivate(self) -> None:
        published = self.publisher.list_published()
        self.load_registry()
        active_nodes = [node for node, pub in published.items() if pub.get("has_bin")]
        if not active_nodes:
            return

        # Only query HA states if at least one active node uses on_success mode
        needs_ha_states = any(
            ((self.registered.get(node) or {}).get("auto_deactivate") or {}).get("mode", "on_success") == "on_success"
            for node in active_nodes
        )
        update_entities: dict[str, dict[str, Any]] = {}
        if needs_ha_states and self.session and not self.session.closed:
            try:
                update_entities = await supervisor.fetch_update_entities(self.session)
            except Exception as err:
                LOG.debug("Failed to fetch update entities: %s", err)

        now = datetime.now(timezone.utc)
        changed = False
        for node in active_nodes:
            rec = self.registered.get(node) or {}
            ad = rec.get("auto_deactivate") or {"mode": "on_success", "timer_hours": 12}
            mode = ad.get("mode", "on_success")
            if mode == "none":
                continue

            expires_at_str = ad.get("expires_at")
            pub = published.get(node) or {}
            pub_ver = pub.get("version")

            # 1. Timer check (applicable to both 'timer' mode and fallback on 'on_success')
            if expires_at_str:
                try:
                    expires_at = datetime.fromisoformat(expires_at_str)
                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=timezone.utc)
                    if now >= expires_at:
                        self.deactivate_firmware(node)
                        registry.set_auto_deactivate(
                            self.registered,
                            node,
                            mode,
                            ad.get("timer_hours", 12),
                            expires_at=None,
                            last_status=f"Auto-hidden by timer ({ad.get('timer_hours', 12)}h elapsed)",
                        )
                        changed = True
                        LOG.info("Auto-deactivated %s (timer expired at %s)", node, expires_at_str)
                        continue
                except Exception as err:
                    LOG.warning(
                        "Auto-deactivate timer check failed for %s (expires_at=%r): %s",
                        node,
                        expires_at_str,
                        err,
                    )

            # 2. On-success check
            if mode == "on_success" and pub_ver and update_entities:
                matched = self.match_ha_update_entity(
                    node, rec.get("title") or node, rec.get("ha_entity_id"), update_entities
                )
                if matched:
                    installed_ver = (matched.get("installed_version") or "").strip()
                    in_progress = bool(matched.get("in_progress"))
                    if installed_ver == pub_ver and not in_progress:
                        self.deactivate_firmware(node)
                        registry.set_auto_deactivate(
                            self.registered,
                            node,
                            mode,
                            ad.get("timer_hours", 12),
                            expires_at=None,
                            last_status=f"Auto-hidden after successful update to {pub_ver}",
                        )
                        changed = True
                        LOG.info(
                            "Auto-deactivated %s after HA reported installed version %s",
                            node,
                            installed_ver,
                        )

        if changed:
            self.save_registry()

    def unpublish_firmware(self, node: str) -> None:
        token = (self.registered.get(node) or {}).get("token") or ""
        self.publisher.delete_binary(node, token=token)

    def unregister_device(self, node: str) -> None:
        token = (self.registered.get(node) or {}).get("token") or ""
        self.registered.pop(node, None)
        self.save_registry()
        self.publisher.unpublish(node, token=token)
        packages.delete_device_wrappers(self.settings.esphome_config_dir, node)

    def wrapper_version_for(self, node: str) -> str:
        rec = self.registered.get(node) or {}
        return packages.normalize_version(rec.get("version") or "") or "1.0.0"

    def write_device_wrapper(self, node: str, version: str | None = None) -> str:
        """Create/update this device's snippet YAML. Not called until publish or snippet."""
        rec = self.registered.get(node) or {}
        token = rec.get("token") or ""
        ver = packages.normalize_version(version or "") or self.wrapper_version_for(node)
        if node in self.registered:
            self.registered[node]["version"] = ver
            self.save_registry()
        packages.write_one_device_wrapper(self.settings.esphome_config_dir, node, ver, token=token)
        return ver

    def advance_registered_version(self, node: str, published_version: str) -> None:
        """After a publish, raise the wrapper so the next compile is a new update."""
        rec = self.registered.get(node)
        current = (rec or {}).get("version") or published_version
        nxt = (
            current
            if current != published_version
            else packages.bump_version(published_version)
        )
        registry.upsert(self.registered, node, nxt, (rec or {}).get("title") or "")
        self.save_registry()
        self.write_device_wrapper(node, nxt)

    async def _dashboard_esphome_version(self) -> str:
        if self.esphome_version:
            return self.esphome_version
        try:
            async with self._client() as client:
                self.esphome_version = client.server_info.get("esphome_version", "") or ""
        except DashboardError:
            pass
        return self.esphome_version

    async def list_devices(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
        """Registered devices for the table; unpublished YAML only for the register form.

        Register first (YAML + version). That row stays after you leave to
        compile. Publish the .bin from the row.
        """
        self.load_registry()
        configs, _stems = metadata.scan_esphome_dir(self.settings.esphome_config_dir)
        published = self.publisher.list_published()
        local = {row["node"]: row for row in configs}

        update_entities: dict[str, dict[str, Any]] = {}
        try:
            if self.session and not self.session.closed:
                update_entities = await supervisor.fetch_update_entities(self.session)
            else:
                async with aiohttp.ClientSession() as session:
                    update_entities = await supervisor.fetch_update_entities(session)
        except Exception as err:
            LOG.debug("Could not fetch HA update entities: %s", err)

        dashboard_by_node: dict[str, dict[str, Any]] = {}
        dashboard_error: str | None = None
        try:
            async with self._client() as client:
                self.esphome_version = client.server_info.get("esphome_version", "") or self.esphome_version
                for device in await client.devices():
                    configuration = device.get("configuration", "")
                    node = metadata.node_from_configuration(configuration)
                    family = metadata.chip_family_from_platform(
                        device.get("target_platform", "") or local.get(node, {}).get("target_platform", "")
                    )
                    dashboard_by_node[node] = {
                        "configuration": configuration,
                        "friendly_name": device.get("friendly_name") or node,
                        "target_platform": device.get("target_platform", ""),
                        "chip_family": family,
                        "device_version": device.get("current_version", ""),
                        "has_binary": await client.has_ota_binary(configuration),
                    }
        except DashboardError as err:
            dashboard_error = str(err)

        nodes = set(self.registered) | set(published)
        rows: list[dict[str, Any]] = []
        for node in nodes:
            if not metadata.NODE_RE.match(node):
                continue
            record = published.get(node)
            local_row = local.get(node, {})
            dash = dashboard_by_node.get(node, {})
            rec = self.registered.get(node, {})
            friendly = (
                dash.get("friendly_name")
                or local_row.get("friendly_name")
                or rec.get("title")
                or (record.get("title") if record else None)
                or node
            )
            own_version = local_row.get("own_project_version")
            project_version = rec.get("version") or own_version or (
                metadata.wrapper_project_version(self.settings.esphome_config_dir, node)
                if packages.device_wrapper_exists(self.settings.esphome_config_dir, node)
                else None
            )
            has_yaml = bool(node in local or metadata.find_configuration(self.settings.esphome_config_dir, node))
            injected = metadata.is_injected(self.settings.esphome_config_dir, node)
            matched_ha = self.match_ha_update_entity(
                node, friendly, rec.get("ha_entity_id"), update_entities
            )

            token = rec.get("token") or ""
            slug = f"{node}_{token}" if token else node
            rows.append(
                {
                    "node": node,
                    "token": token,
                    "slug": slug,
                    "configuration": dash.get("configuration") or local_row.get("configuration"),
                    "friendly_name": friendly,
                    "target_platform": dash.get("target_platform") or local_row.get("target_platform", ""),
                    "chip_family": (record or {}).get("chip_family")
                    or dash.get("chip_family")
                    or local_row.get("chip_family"),
                    "project_version": project_version,
                    "own_project_version": own_version,
                    "device_version": dash.get("device_version", ""),
                    "has_binary": bool(dash.get("has_binary")),
                    "published": record,
                    "registered": node in self.registered,
                    "manual": node not in dashboard_by_node and node not in local,
                    "source": (
                        "dashboard"
                        if node in dashboard_by_node
                        else ("yaml" if node in local else "published")
                    ),
                    "has_yaml": has_yaml,
                    "injected": injected,
                    "ha_entity": matched_ha,
                    "auto_deactivate": rec.get("auto_deactivate") or {
                        "mode": "on_success",
                        "timer_hours": 12,
                        "expires_at": None,
                        "last_status": None,
                    },
                    "summary": (record or {}).get("summary") or rec.get("summary") or "",
                    "publishable": True,
                }
            )

        rows.sort(key=lambda r: r["friendly_name"].lower())
        return rows, configs, dashboard_error

    # -- jobs --------------------------------------------------------------

    def start_job(self, node: str, configuration: str, compile_first: bool, summary: str = "") -> Job:
        job = Job(node, "build" if compile_first else "publish")
        self.jobs[job.id] = job
        asyncio.create_task(self._run_job(job, configuration, compile_first, summary=summary))
        return job

    async def _run_job(
        self, job: Job, configuration: str, compile_first: bool, summary: str = ""
    ) -> None:
        # One build at a time: the dashboard's compile lane is a single worker
        # anyway, and queueing here keeps our own log readable.
        async with self.lock:
            job.status = "running"
            try:
                device: dict = {}
                esphome_version = ""
                async with self._client() as client:
                    if compile_first:
                        self.write_device_wrapper(job.node)
                        job.log(f"Building {configuration} ...")
                        await client.compile(configuration, on_output=job.log)
                        job.log("Build finished.")
                    elif not await client.has_ota_binary(configuration):
                        raise DashboardError(
                            f"{configuration} has no firmware.ota.bin yet — build it first."
                        )

                    job.log("Downloading firmware.ota.bin ...")
                    blob = await client.download_ota(configuration)
                    job.log(f"Downloaded {len(blob)} bytes.")
                    esphome_version = client.server_info.get("esphome_version", "")
                    if esphome_version:
                        self.esphome_version = esphome_version
                    device = next(
                        (d for d in await client.devices() if d.get("configuration") == configuration),
                        {},
                    )

                target_platform = device.get("target_platform", "")
                is_valid, msg, info = metadata.validate_binary(blob, target_platform, MAX_UPLOAD_BYTES)
                if not is_valid:
                    raise DashboardError(f"Firmware binary validation failed: {msg}")

                app_desc = info.get("app_descriptor") or {}
                if app_desc.get("idf_version"):
                    job.log(f"ESP-IDF {app_desc['idf_version']} app descriptor verified")

                config = metadata.read_config(self.settings.esphome_config_dir, configuration)
                origin = self.settings.esphome_config_dir / configuration
                family, source = metadata.chip_family(target_platform, blob)
                if not family:
                    raise DashboardError(
                        f"Could not determine chipFamily for {configuration} "
                        f"(target_platform={device.get('target_platform', '?')!r})."
                    )
                job.log(f"chipFamily: {family} (from {source})")

                version = metadata.effective_project_version(
                    self.settings.esphome_config_dir, job.node, config, origin
                )
                if version:
                    job.log(f"version: {version} (esphome.project.version)")
                else:
                    version = esphome_version or "0.0.0"
                    job.log(
                        f"version: {version} (ESPHome release — no esphome.project block, so the "
                        f"update entity will only fire when ESPHome itself is upgraded)"
                    )

                title = device.get("friendly_name") or job.node
                token = (self.registered.get(job.node) or {}).get("token") or ""
                record = self.publisher.publish(
                    node=job.node,
                    blob=blob,
                    chip_family=family,
                    version=version,
                    title=title,
                    summary=summary,
                    token=token,
                )
                slug_name = record.get("slug") or job.node
                job.log(
                    f"Published {record['size']} bytes, md5 {record['md5'][:8]} — "
                    f"{self.resolved_base_url}/local/{self.settings.publish_dir}/{slug_name}.json"
                )
                self.advance_registered_version(job.node, version)
                self._schedule_auto_deactivate(job.node)
                job.status = "completed"
            except Exception as err:  # noqa: BLE001 - surfaced to the UI verbatim
                LOG.exception("Job %s failed", job.id)
                job.error = str(err)
                job.status = "failed"


# -- routes ----------------------------------------------------------------

routes = web.RouteTableDef()


@routes.get("/")
async def index(_: web.Request) -> web.FileResponse:
    return web.FileResponse(HERE / "static" / "index.html")


@routes.get("/api/status")
async def status(request: web.Request) -> web.Response:
    app: App = request.app["app"]
    return web.json_response(
        {
            "dashboard": app.resolved_dashboard,
            "base_url": app.resolved_base_url,
            "base_url_source": app.base_url_source,
            "publish_dir": app.settings.publish_dir,
            "restart_required": app.restart_required,
            "package_dir": packages.PACKAGE_DIR,
            "chip_families": metadata.CHIP_FAMILIES,
            "esphome_version": app.esphome_version,
            "addon_version": app.addon_version,
        }
    )


@routes.get("/api/devices")
async def devices(request: web.Request) -> web.Response:
    app: App = request.app["app"]
    rows, configs, dashboard_error = await app.list_devices()
    if dashboard_error:
        LOG.warning("Listing dashboard devices failed (showing published-only rows): %s", dashboard_error)
    return web.json_response(
        {"devices": rows, "configs": configs, "dashboard_error": dashboard_error, "esphome_version": app.esphome_version}
    )


@routes.post("/api/publish")
async def publish(request: web.Request) -> web.Response:
    app: App = request.app["app"]
    body = await request.json()
    configuration = body.get("configuration", "")
    summary = (body.get("summary") or "").strip()
    if not configuration or "/" in configuration or not (
        configuration.endswith(".yaml") or configuration.endswith(".yml")
    ):
        return web.json_response({"error": "invalid configuration"}, status=400)
    node = metadata.node_from_configuration(configuration)
    job = app.start_job(node, configuration, bool(body.get("compile")), summary=summary)
    return web.json_response(job.as_dict())


@routes.get("/api/jobs/{job_id}")
async def job_status(request: web.Request) -> web.Response:
    app: App = request.app["app"]
    job = app.jobs.get(request.match_info["job_id"])
    if job is None:
        return web.json_response({"error": "unknown job"}, status=404)
    return web.json_response(job.as_dict())


@routes.get("/api/snippet")
async def snippet(request: web.Request) -> web.Response:
    app: App = request.app["app"]
    node = request.query.get("node", "")
    if not node:
        return web.json_response({"error": "node required"}, status=400)
    override = packages.normalize_version(request.query.get("version", ""))
    if not override and node in app.registered:
        override = packages.normalize_version(app.registered[node].get("version") or "")
    version = app.write_device_wrapper(node, override)
    published = app.publisher.published(node)
    published_version = published.get("version") if published else None
    return web.json_response(
        {
            "snippet": packages.snippet(node, published_version, has_wrapper=True),
            "legacy": packages.single_entity_snippets(
                node, published_version, has_wrapper=True
            ),
            "uses_wrapper": True,
            "has_project": True,
            "version": version,
        }
    )


@routes.post("/api/register")
async def register_device(request: web.Request) -> web.Response:
    app: App = request.app["app"]
    try:
        body = await request.json()
    except ValueError:
        return web.json_response({"error": "invalid json"}, status=400)
    node = (body.get("node") or "").strip()
    version = packages.normalize_version(body.get("version") or "") or "1.0.0"
    title = (body.get("title") or "").strip()
    summary = (body.get("summary") or "").strip()
    if not metadata.NODE_RE.match(node):
        return web.json_response(
            {"error": "node must be the YAML filename without extension (letters, digits, hyphen, underscore)"},
            status=400,
        )
    app.load_registry()
    if node in app.registered:
        return web.json_response({"error": "already registered — publish from the list"}, status=409)
    rec = app.register_device(node, version, title)
    if summary:
        rec["summary"] = summary
        app.save_registry()
    return web.json_response({"node": node, "version": rec["version"], "title": rec.get("title") or node})


@routes.post("/api/wrapper-version")
async def wrapper_version(request: web.Request) -> web.Response:
    """Set the wrapper's esphome.project.version so the next compile uses it."""
    app: App = request.app["app"]
    try:
        body = await request.json()
    except ValueError:
        return web.json_response({"error": "invalid json"}, status=400)
    node = (body.get("node") or "").strip()
    version = packages.normalize_version(body.get("version") or "")
    if not metadata.NODE_RE.match(node):
        return web.json_response({"error": "invalid node"}, status=400)
    if not version:
        return web.json_response({"error": "invalid version"}, status=400)
    if node not in app.registered:
        return web.json_response({"error": "register this device first"}, status=404)
    rec = app.register_device(node, version)
    app.write_device_wrapper(node, version)
    return web.json_response({"node": node, "version": rec["version"], "wrapper": True})


@routes.post("/api/device/inject")
async def inject_device(request: web.Request) -> web.Response:
    """One-click inject OTA package include into the device YAML."""
    app: App = request.app["app"]
    try:
        body = await request.json()
    except ValueError:
        return web.json_response({"error": "invalid json"}, status=400)
    node = (body.get("node") or "").strip()
    if not metadata.NODE_RE.match(node):
        return web.json_response({"error": "invalid node"}, status=400)

    # Ensure wrapper exists
    version = app.wrapper_version_for(node)
    app.write_device_wrapper(node, version)

    ok, msg = metadata.inject_device_wrapper(app.settings.esphome_config_dir, node)
    if not ok:
        return web.json_response({"error": msg}, status=400)
    return web.json_response({"ok": True, "node": node, "injected": True, "message": msg})


@routes.post("/api/device/eject")
async def eject_device(request: web.Request) -> web.Response:
    """Remove OTA package include from the device YAML."""
    app: App = request.app["app"]
    try:
        body = await request.json()
    except ValueError:
        return web.json_response({"error": "invalid json"}, status=400)
    node = (body.get("node") or "").strip()
    if not metadata.NODE_RE.match(node):
        return web.json_response({"error": "invalid node"}, status=400)

    ok, msg = metadata.eject_device_wrapper(app.settings.esphome_config_dir, node)
    if not ok:
        return web.json_response({"error": msg}, status=400)
    return web.json_response({"ok": True, "node": node, "injected": False, "message": msg})


@routes.post("/api/device/auto-deactivate")
async def set_auto_deactivate_route(request: web.Request) -> web.Response:
    """Configure auto-deactivate mode and timer for a device."""
    app: App = request.app["app"]
    try:
        body = await request.json()
    except ValueError:
        return web.json_response({"error": "invalid json"}, status=400)
    node = (body.get("node") or "").strip()
    mode = body.get("mode", "on_success")
    ha_entity_id = body.get("ha_entity_id")

    if not metadata.NODE_RE.match(node):
        return web.json_response({"error": "invalid node"}, status=400)
    if mode not in ("on_success", "timer", "none"):
        return web.json_response({"error": "invalid mode"}, status=400)

    try:
        timer_hours = int(body.get("timer_hours", 12))
        if not (1 <= timer_hours <= 720):
            raise ValueError()
    except (ValueError, TypeError):
        return web.json_response({"error": "timer_hours must be an integer between 1 and 720"}, status=400)

    app.load_registry()
    filename = metadata.find_configuration(app.settings.esphome_config_dir, node)
    if not filename and node not in app.registered:
        return web.json_response({"error": f"node '{node}' is not a registered or discovered device"}, status=404)

    published = app.publisher.list_published()
    pub = published.get(node) or {}
    now = datetime.now(timezone.utc)
    if pub.get("has_bin") and mode in ("on_success", "timer"):
        expires_at = (now + timedelta(hours=timer_hours)).isoformat(timespec="seconds")
    else:
        expires_at = None

    registry.set_auto_deactivate(
        app.registered,
        node,
        mode,
        timer_hours,
        expires_at=expires_at,
        last_status="Active (monitoring update)" if (pub.get("has_bin") and mode != "none") else None,
    )
    if "ha_entity_id" in body:
        registry.set_ha_entity_id(app.registered, node, ha_entity_id if ha_entity_id else None)
    app.save_registry()
    return web.json_response({
        "ok": True,
        "node": node,
        "auto_deactivate": app.registered[node].get("auto_deactivate"),
        "ha_entity_id": app.registered[node].get("ha_entity_id"),
    })


@routes.get("/api/ha/update-entities")
async def get_ha_update_entities(request: web.Request) -> web.Response:
    """Fetch all HA update.* entities."""
    app: App = request.app["app"]
    session = app.session if app.session and not app.session.closed else None
    if session:
        entities = await supervisor.fetch_update_entities(session)
    else:
        async with aiohttp.ClientSession() as sess:
            entities = await supervisor.fetch_update_entities(sess)
    return web.json_response({"entities": list(entities.values())})


@routes.post("/api/batch")
async def batch_action(request: web.Request) -> web.Response:
    """Perform batch actions across multiple devices."""
    app: App = request.app["app"]
    try:
        body = await request.json()
    except ValueError:
        return web.json_response({"error": "invalid json"}, status=400)
    nodes = body.get("nodes") or []
    action = (body.get("action") or "").strip()
    if not isinstance(nodes, list) or not action:
        return web.json_response({"error": "nodes and action required"}, status=400)

    results: dict[str, Any] = {}
    for node in nodes:
        if not isinstance(node, str) or not metadata.NODE_RE.match(node):
            continue
        try:
            if action == "deactivate":
                app.deactivate_firmware(node)
                results[node] = {"ok": True, "active": False}
            elif action == "activate":
                app.activate_firmware(node)
                results[node] = {"ok": True, "active": True}
            elif action == "inject":
                ver = app.wrapper_version_for(node)
                app.write_device_wrapper(node, ver)
                ok, msg = metadata.inject_device_wrapper(app.settings.esphome_config_dir, node)
                results[node] = {"ok": ok, "message": msg}
            elif action == "eject":
                ok, msg = metadata.eject_device_wrapper(app.settings.esphome_config_dir, node)
                results[node] = {"ok": ok, "message": msg}
            elif action == "delete":
                app.unregister_device(node)
                results[node] = {"ok": True}
            else:
                return web.json_response({"error": f"unknown action: {action}"}, status=400)
        except Exception as err:
            results[node] = {"ok": False, "error": str(err)}

    return web.json_response({"ok": True, "action": action, "results": results})


NODE_RE = metadata.NODE_RE
MAX_UPLOAD_BYTES = 32 * 1024 * 1024  # allows 16MB/32MB flash target builds


@routes.post("/api/publish/manual")
async def publish_manual(request: web.Request) -> web.Response:
    """Publish a firmware.ota.bin the operator downloaded from the ESPHome
    dashboard themselves — the path that needs no WS connection to ESPHome at
    all, for anyone who won't open ESPHome's public port for this add-on.
    """
    app: App = request.app["app"]
    reader = await request.multipart()

    node = title = version = chip_family = summary = ""
    blob = b""

    field = await reader.next()
    while field is not None:
        if field.name == "file":
            chunks = []
            total = 0
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    return web.json_response({"error": "file too large"}, status=413)
                chunks.append(chunk)
            blob = b"".join(chunks)
        elif field.name in ("node", "title", "version", "chip_family", "summary"):
            value = (await field.text()).strip()
            if field.name == "node":
                node = value
            elif field.name == "title":
                title = value
            elif field.name == "version":
                version = value
            elif field.name == "chip_family":
                chip_family = value
            elif field.name == "summary":
                summary = value
        field = await reader.next()

    if not NODE_RE.match(node):
        return web.json_response(
            {"error": "node must be the YAML filename without extension (letters, digits, hyphen, underscore)"},
            status=400,
        )
    if not blob:
        return web.json_response({"error": "file required"}, status=400)

    # Validate binary integrity and structure with platform context
    is_valid, val_msg, info = metadata.validate_binary(blob, chip_family, MAX_UPLOAD_BYTES)
    if not is_valid:
        return web.json_response({"error": f"Firmware validation error: {val_msg}"}, status=400)

    app_desc = info.get("app_descriptor") or {}
    if app_desc.get("idf_version"):
        LOG.info("Manual publish %s: ESP-IDF %s app descriptor verified", node, app_desc["idf_version"])

    if not chip_family and info.get("chip_family"):
        chip_family = info["chip_family"]

    filename = metadata.find_configuration(app.settings.esphome_config_dir, node)
    config: dict = {}
    origin = app.settings.esphome_config_dir / (filename or f"{node}.yaml")
    merged: dict = {}
    uses_wrapper = False
    cache: dict = {}
    if filename:
        config = metadata.read_config(app.settings.esphome_config_dir, filename)
        merged, uses_wrapper = metadata.merge_config(
            app.settings.esphome_config_dir, config, origin, skip_wrapper_node=node, cache=cache
        )
    own = metadata.project_version(merged)
    compiled = own or (
        metadata.wrapper_project_version(app.settings.esphome_config_dir, node) if uses_wrapper else None
    )
    requested = version
    version_source = "supplied"
    if app_desc.get("version"):
        version = app_desc["version"]
        version_source = "binary"
    elif requested:
        version = requested
        version_source = "supplied"
    elif compiled:
        version = compiled
        version_source = "project"
    else:
        pub = app.publisher.published(node)
        if pub and pub.get("version"):
            version = pub["version"]
            version_source = "published"
        else:
            esphome_version = await app._dashboard_esphome_version()
            version = esphome_version or "1.0.0"
            version_source = "fallback"
    if not version:
        return web.json_response(
            {
                "error": "version required — firmware has no project.version; "
                "pass the ESPHome release this binary was compiled with"
            },
            status=400,
        )
    if filename and not title:
        title = metadata.friendly_name(merged, node)
    elif not title:
        title = node

    # The image header knows the chip; the operator only has a dropdown and a
    # memory of which board this .bin came from. Read it out and let the form
    # value be the fallback — for targets with no chip_id in the header
    # (ESP8266/RP2040) and for a chip newer than CHIP_IDS.
    sniffed = metadata.chip_family_from_binary(blob)
    if sniffed and chip_family and sniffed != chip_family:
        LOG.warning(
            "Manual publish %s: form says %s, image header says %s — trusting the header",
            node,
            chip_family,
            sniffed,
        )
    chip_family = sniffed or chip_family
    if chip_family not in metadata.CHIP_FAMILIES:
        return web.json_response(
            {"error": "could not read chipFamily from the firmware — select one explicitly"},
            status=400,
        )

    token = (app.registered.get(node) or {}).get("token") or ""
    record = app.publisher.publish(
        node=node,
        blob=blob,
        chip_family=chip_family,
        version=version,
        title=title or node,
        summary=summary,
        token=token,
    )
    record["version_source"] = version_source
    if requested and requested != version:
        record["version_overridden"] = True
        record["requested_version"] = requested
    LOG.info("Manually published %s (%s, %s bytes, %s, slug=%s)", node, chip_family, record["size"], version, record.get("slug"))
    app.advance_registered_version(node, version)
    app._schedule_auto_deactivate(node)
    return web.json_response(record)


@routes.post("/api/firmware/deactivate")
@routes.delete("/api/firmware/{node}")
@routes.delete("/api/unpublish/{node}")
async def deactivate_firmware_route(request: web.Request) -> web.Response:
    app: App = request.app["app"]
    node = request.match_info.get("node")
    if not node:
        try:
            body = await request.json()
            node = body.get("node")
        except Exception:
            pass
    node = (node or "").strip()
    if not node or "/" in node or node.startswith("."):
        return web.json_response({"error": "invalid node"}, status=400)
    app.deactivate_firmware(node)
    LOG.info("Deactivated firmware for %s (removed from /local, kept in storage)", node)
    return web.json_response({"ok": True, "node": node, "active": False})


@routes.post("/api/firmware/activate")
async def activate_firmware_route(request: web.Request) -> web.Response:
    app: App = request.app["app"]
    node = request.match_info.get("node")
    if not node:
        try:
            body = await request.json()
            node = body.get("node")
        except Exception:
            pass
    node = (node or "").strip()
    if not node or "/" in node or node.startswith("."):
        return web.json_response({"error": "invalid node"}, status=400)
    try:
        app.activate_firmware(node)
    except FileNotFoundError as err:
        return web.json_response({"error": str(err)}, status=404)
    LOG.info("Activated firmware for %s (deployed to /local)", node)
    return web.json_response({"ok": True, "node": node, "active": True})


@routes.delete("/api/device/{node}")
@routes.delete("/api/publish/{node}")
async def unregister(request: web.Request) -> web.Response:
    app: App = request.app["app"]
    node = request.match_info["node"]
    if "/" in node or node.startswith("."):
        return web.json_response({"error": "invalid node"}, status=400)
    app.unregister_device(node)
    LOG.info("Unregistered device %s", node)
    return web.json_response({"ok": True, "node": node})


def create_app() -> web.Application:
    # Default is 1MB, well under any real firmware — raised for /api/publish/manual.
    app = web.Application(client_max_size=MAX_UPLOAD_BYTES + 65536)
    instance = App()
    app["app"] = instance
    app.on_startup.append(instance.startup)
    app.on_cleanup.append(instance.shutdown)
    app.add_routes(routes)
    return app

