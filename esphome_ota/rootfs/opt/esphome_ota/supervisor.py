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

# The Supervisor bridge gateway — the address that reaches a host-published
# port (like ESPHome's mapped 6052) from a sibling container.
#
# Deliberately NOT used to reach device-builder's "trusted" ingress site.
# That site's ingress_peer_guard middleware only admits loopback and the
# Supervisor container's own fixed address (172.30.32.2) — it exists to let
# HA's authenticated-browser Ingress proxy through, not sibling add-ons.
# Any other source IP, gateway included, gets HTTP 403 on the WS handshake.
# The only route in is ESPHome's public port with its explicit
# "leave_front_door_open" + mapped-port opt-in (see find_dashboard_url).
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

    Only the mapped public port (6052) is reachable from here — see the
    HOST_GATEWAY note above for why the ingress port is not an option.
    Requires the ESPHome add-on to have "leave_front_door_open" enabled
    *and* port 6052 mapped; without both, device-builder refuses to bind
    the public port at all (falls back to ingress-only), so a candidate
    with no mapped port is not a partial match — it means the operator
    still needs to flip that switch.
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

    found_unmapped = False
    for slug in candidates:
        try:
            info = await _get(session, f"/addons/{slug}/info")
        except Exception as err:  # noqa: BLE001
            LOG.warning("Could not read info for add-on %s: %s", slug, err)
            continue

        network = info.get("network") or {}
        # Logged at info level (not debug) because this is exactly the fact
        # needed to tell "not mapped yet" apart from "mapped, but this add-on
        # is somehow still not seeing it" — the two look identical from the
        # outside otherwise.
        LOG.info("%s network map from Supervisor: %s", slug, network)
        for container_port, host_port in network.items():
            if container_port.startswith("6052") and host_port:
                url = f"http://{HOST_GATEWAY}:{host_port}"
                LOG.info("Found ESPHome dashboard (%s) on public port %s", slug, url)
                return url
        found_unmapped = True

    if found_unmapped:
        LOG.warning(
            'Found an ESPHome add-on, but port 6052 isn\'t mapped (or "leave_front_door_open" '
            "isn't on) — its public port isn't bound, so it can't be reached from here. See "
            "DOCS.md."
        )
    else:
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
