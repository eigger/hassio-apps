"""Ingress web app: list devices, build, publish."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web

import metadata
import packages
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
    def __init__(self) -> None:
        self.settings = Settings()
        self.publisher = Publisher(self.settings.www_root, self.settings.publish_dir)
        self.resolved_dashboard: str = ""
        self.resolved_base_url: str = ""
        self.base_url_source: str = ""
        self.restart_required = False
        self.jobs: dict[str, Job] = {}
        self.lock = asyncio.Lock()
        self.esphome_version: str = ""

    # -- startup -----------------------------------------------------------

    async def startup(self, _: web.Application) -> None:
        self.restart_required = self.publisher.ensure_dirs()

        async with aiohttp.ClientSession() as session:
            if self.settings.dashboard_url:
                self.resolved_dashboard = self.settings.dashboard_url.rstrip("/")
            else:
                self.resolved_dashboard = await supervisor.find_dashboard_url(session) or ""

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
                external_url = await supervisor.find_external_url(session)
                if external_url:
                    self.resolved_base_url = external_url.rstrip("/")
                    self.base_url_source = "ha_external_url"
                else:
                    host_ip = await supervisor.find_host_ip(session)
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
            self.sync_device_wrappers()
        else:
            LOG.error(
                "Could not determine Home Assistant's address. Set 'base_url' in the add-on "
                "options (for example https://your-tunnel-domain) so the packages can be written."
            )

    # -- dashboard ---------------------------------------------------------

    def _client(self) -> DashboardClient:
        if not self.resolved_dashboard:
            raise DashboardError(
                "No ESPHome dashboard found. Make sure the ESPHome Device Builder add-on is "
                "running, or set 'dashboard_url' in the add-on options."
            )
        return DashboardClient(self.resolved_dashboard, self.settings.dashboard_token)

    def sync_device_wrappers(
        self,
        bump_nodes: set[str] | None = None,
        overrides: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        configs, stems = metadata.scan_esphome_dir(self.settings.esphome_config_dir)
        published = self.publisher.list_published()
        bump_nodes = bump_nodes or set()
        overrides = overrides or {}
        devices = []
        for row in configs:
            if not row.get("publishable"):
                continue
            node = row["node"]
            override = overrides.get(node)
            version = packages.next_firmware_version(
                row.get("own_project_version"),
                (published.get(node) or {}).get("version"),
                metadata.wrapper_project_version(self.settings.esphome_config_dir, node),
                bump=node in bump_nodes and not override,
                override=override,
            )
            devices.append({"node": node, "version": version})
            row["project_version"] = version
        packages.write_device_wrappers(
            self.settings.esphome_config_dir,
            devices,
            keep_stems=stems,
        )
        return configs

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
        """Published firmware for the table; local YAML only for the manual form.

        Unpublished YAML files are not table rows. After a successful publish
        they show up because a manifest exists on disk.
        """
        configs = self.sync_device_wrappers()
        published = self.publisher.list_published()
        local = {row["node"]: row for row in configs}

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

        rows: list[dict[str, Any]] = []
        for node, record in published.items():
            local_row = local.get(node, {})
            dash = dashboard_by_node.get(node, {})
            own_version = local_row.get("own_project_version")
            rows.append(
                {
                    "node": node,
                    "configuration": dash.get("configuration") or local_row.get("configuration"),
                    "friendly_name": dash.get("friendly_name")
                    or local_row.get("friendly_name")
                    or record.get("title")
                    or node,
                    "target_platform": dash.get("target_platform") or local_row.get("target_platform", ""),
                    "chip_family": record.get("chip_family")
                    or dash.get("chip_family")
                    or local_row.get("chip_family"),
                    "project_version": own_version,
                    "own_project_version": own_version,
                    "device_version": dash.get("device_version", ""),
                    "has_binary": bool(dash.get("has_binary")),
                    "published": record,
                    "manual": node not in dashboard_by_node and node not in local,
                    "source": (
                        "dashboard"
                        if node in dashboard_by_node
                        else ("yaml" if node in local else "published")
                    ),
                    "publishable": bool(metadata.NODE_RE.match(node)),
                }
            )

        rows.sort(key=lambda r: r["friendly_name"].lower())
        return rows, configs, dashboard_error

    # -- jobs --------------------------------------------------------------

    def start_job(self, node: str, configuration: str, compile_first: bool) -> Job:
        job = Job(node, "build" if compile_first else "publish")
        self.jobs[job.id] = job
        asyncio.create_task(self._run_job(job, configuration, compile_first))
        return job

    async def _run_job(self, job: Job, configuration: str, compile_first: bool) -> None:
        # One build at a time: the dashboard's compile lane is a single worker
        # anyway, and queueing here keeps our own log readable.
        async with self.lock:
            try:
                async with self._client() as client:
                    if compile_first:
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

                config = metadata.read_config(self.settings.esphome_config_dir, configuration)
                origin = self.settings.esphome_config_dir / configuration
                family, source = metadata.chip_family(device.get("target_platform", ""), blob)
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

                record = self.publisher.publish(
                    node=job.node,
                    blob=blob,
                    chip_family=family,
                    version=version,
                    title=device.get("friendly_name") or job.node,
                )
                job.log(
                    f"Published {record['size']} bytes, md5 {record['md5'][:8]} — "
                    f"{self.resolved_base_url}/local/{self.settings.publish_dir}/{job.node}.json"
                )
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
    if not configuration or "/" in configuration or not (
        configuration.endswith(".yaml") or configuration.endswith(".yml")
    ):
        return web.json_response({"error": "invalid configuration"}, status=400)
    node = metadata.node_from_configuration(configuration)
    job = app.start_job(node, configuration, bool(body.get("compile")))
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
    configs = app.sync_device_wrappers(
        bump_nodes=set() if override else {node},
        overrides={node: override} if override else None,
    )
    published = app.publisher.published(node)
    published_version = published.get("version") if published else None
    has_wrapper = packages.device_wrapper_exists(app.settings.esphome_config_dir, node)
    version = next(
        (row.get("project_version") for row in configs if row.get("node") == node),
        None,
    ) or metadata.wrapper_project_version(app.settings.esphome_config_dir, node)
    return web.json_response(
        {
            "snippet": packages.snippet(
                node, published_version, has_wrapper=has_wrapper
            ),
            "legacy": packages.single_entity_snippets(
                node, published_version, has_wrapper=has_wrapper
            ),
            "uses_wrapper": has_wrapper,
            "has_project": bool(has_wrapper and version),
            "version": version or packages.next_firmware_version(
                None, published_version, published_version, bump=True
            ),
        }
    )


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
    configs = app.sync_device_wrappers(overrides={node: version})
    written = next(
        (row.get("project_version") for row in configs if row.get("node") == node),
        None,
    )
    return web.json_response({
        "node": node,
        "version": written or version,
        "wrapper": bool(written),
    })


NODE_RE = metadata.NODE_RE
MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # generous for any ESPHome target; caps abuse


@routes.post("/api/publish/manual")
async def publish_manual(request: web.Request) -> web.Response:
    """Publish a firmware.ota.bin the operator downloaded from the ESPHome
    dashboard themselves — the path that needs no WS connection to ESPHome at
    all, for anyone who won't open ESPHome's public port for this add-on.
    """
    app: App = request.app["app"]
    reader = await request.multipart()

    node = title = version = chip_family = ""
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
        elif field.name in ("node", "title", "version", "chip_family"):
            value = (await field.text()).strip()
            if field.name == "node":
                node = value
            elif field.name == "title":
                title = value
            elif field.name == "version":
                version = value
            elif field.name == "chip_family":
                chip_family = value
        field = await reader.next()

    if not NODE_RE.match(node):
        return web.json_response(
            {"error": "node must be the YAML filename without extension (letters, digits, hyphen, underscore)"},
            status=400,
        )
    if not blob:
        return web.json_response({"error": "file required"}, status=400)

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
    if compiled:
        if requested and requested != compiled:
            LOG.info(
                "Manual publish %s: ignoring form version %s — firmware reports %s",
                node,
                requested,
                compiled,
            )
        version = compiled
        version_source = "project"
    elif not requested:
        esphome_version = await app._dashboard_esphome_version()
        if esphome_version:
            version = esphome_version
            version_source = "esphome"
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

    record = app.publisher.publish(
        node=node, blob=blob, chip_family=chip_family, version=version, title=title or node
    )
    record["version_source"] = version_source
    if requested and requested != version:
        record["version_overridden"] = True
        record["requested_version"] = requested
    LOG.info("Manually published %s (%s, %s bytes, %s)", node, chip_family, record["size"], version)
    return web.json_response(record)


@routes.delete("/api/publish/{node}")
async def unpublish(request: web.Request) -> web.Response:
    app: App = request.app["app"]
    node = request.match_info["node"]
    if "/" in node or node.startswith("."):
        return web.json_response({"error": "invalid node"}, status=400)
    app.publisher.unpublish(node)
    return web.json_response({"ok": True})


def create_app() -> web.Application:
    # Default is 1MB, well under any real firmware — raised for /api/publish/manual.
    app = web.Application(client_max_size=MAX_UPLOAD_BYTES + 65536)
    instance = App()
    app["app"] = instance
    app.on_startup.append(instance.startup)
    app.add_routes(routes)
    return app
