"""Thin Supervisor REST helpers.

Two things are needed from the Supervisor: where the ESPHome Device Builder
dashboard listens, and which LAN address Home Assistant answers on (so the
generated ESPHome packages can point at it).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from aiohttp import ClientSession, ClientTimeout

LOG = logging.getLogger("supervisor")

SUPERVISOR = "http://supervisor"
TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")

# The Supervisor bridge gateway — i.e. the host. The ESPHome add-on runs with
# host_network, and device-builder binds its no-auth ingress site to
# 127.0.0.1 + 172.30.32.1, so this is the address that reaches it from here.
HOST_GATEWAY = "172.30.32.1"

_TIMEOUT = ClientTimeout(total=15)


async def _get(session: ClientSession, path: str) -> Any:
    if not TOKEN:
        raise RuntimeError("SUPERVISOR_TOKEN is not set")
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with session.get(f"{SUPERVISOR}{path}", headers=headers, timeout=_TIMEOUT) as resp:
        resp.raise_for_status()
        payload = await resp.json()
    return payload.get("data")


async def find_dashboard_url(session: ClientSession) -> str | None:
    """Return a base URL for the ESPHome dashboard, or None if not found.

    Prefers the add-on's ingress port: that site skips authentication for
    connections arriving from the Supervisor gateway, so no credentials are
    needed. Falls back to a mapped public port (6052) when one exists.
    """
    try:
        addons = await _get(session, "/addons")
    except Exception as err:  # noqa: BLE001 - any failure means "auto-detect unavailable"
        LOG.warning("Could not list add-ons via Supervisor: %s", err)
        return None

    candidates = [
        a["slug"]
        for a in (addons or {}).get("addons", [])
        if "esphome" in a.get("slug", "") and a.get("state") == "started"
    ]
    # Prefer the stable flavour over -beta / -dev when several are installed.
    candidates.sort(key=lambda slug: (slug.endswith(("-beta", "-dev")), slug))

    for slug in candidates:
        try:
            info = await _get(session, f"/addons/{slug}/info")
        except Exception as err:  # noqa: BLE001
            LOG.warning("Could not read info for add-on %s: %s", slug, err)
            continue

        ingress_port = info.get("ingress_port")
        if ingress_port:
            url = f"http://{HOST_GATEWAY}:{ingress_port}"
            LOG.info("Found ESPHome dashboard (%s) at %s", slug, url)
            return url

        # No ingress port, but the user may have mapped the public port.
        for container_port, host_port in (info.get("network") or {}).items():
            if container_port.startswith("6052") and host_port:
                url = f"http://{HOST_GATEWAY}:{host_port}"
                LOG.info("Found ESPHome dashboard (%s) on public port %s", slug, url)
                return url

    LOG.warning("No running ESPHome add-on found")
    return None


async def find_host_ip(session: ClientSession) -> str | None:
    """Return the host's primary LAN IPv4 address."""
    try:
        info = await _get(session, "/network/info")
    except Exception as err:  # noqa: BLE001
        LOG.warning("Could not read network info: %s", err)
        return None

    interfaces = (info or {}).get("interfaces", [])
    ordered = sorted(interfaces, key=lambda i: not i.get("primary"))
    for iface in ordered:
        if not iface.get("enabled", True):
            continue
        for cidr in ((iface.get("ipv4") or {}).get("address") or []):
            address = cidr.split("/")[0]
            if address and not address.startswith("127."):
                return address
    return None
