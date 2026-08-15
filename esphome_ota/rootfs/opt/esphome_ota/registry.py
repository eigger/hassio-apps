"""Persist which devices the operator registered — independent of published firmware.

The table is this list, so going to ESPHome to compile and coming back does
not lose the device. Publish happens from the row after that.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from packages import PACKAGE_DIR

LOG = logging.getLogger("registry")

REGISTRY_FILE = "registered.json"


def registry_path(esphome_config_dir: Path) -> Path:
    return esphome_config_dir / PACKAGE_DIR / REGISTRY_FILE


def load(esphome_config_dir: Path) -> dict[str, dict[str, Any]]:
    path = registry_path(esphome_config_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as err:
        LOG.warning("Could not read %s: %s", path, err)
        return {}
    if not isinstance(data, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for node, rec in data.items():
        if not isinstance(node, str) or not isinstance(rec, dict):
            continue
        result[node] = rec
    return result


def save(esphome_config_dir: Path, data: dict[str, dict[str, Any]]) -> None:
    path = registry_path(esphome_config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def upsert(
    data: dict[str, dict[str, Any]],
    node: str,
    version: str,
    title: str = "",
    summary: str = "",
    ha_entity_id: str | None = None,
    auto_deactivate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rec = dict(data.get(node) or {})
    rec["version"] = version
    if title:
        rec["title"] = title
    if summary:
        rec["summary"] = summary
    if ha_entity_id is not None:
        rec["ha_entity_id"] = ha_entity_id
    if auto_deactivate is not None:
        rec["auto_deactivate"] = auto_deactivate
    elif "auto_deactivate" not in rec:
        # Default auto_deactivate: on_success mode with 12h fallback timer
        rec["auto_deactivate"] = {
            "mode": "on_success",
            "timer_hours": 12,
            "expires_at": None,
            "last_status": None,
        }
    rec.setdefault("registered_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    data[node] = rec
    return rec


def set_auto_deactivate(
    data: dict[str, dict[str, Any]],
    node: str,
    mode: str,
    timer_hours: int = 12,
    expires_at: str | None = None,
    last_status: str | None = None,
) -> dict[str, Any]:
    rec = dict(data.get(node) or {})
    ad = dict(rec.get("auto_deactivate") or {})
    ad["mode"] = mode
    ad["timer_hours"] = max(1, min(720, int(timer_hours)))
    if expires_at is not None:
        ad["expires_at"] = expires_at
    if last_status is not None:
        ad["last_status"] = last_status
    rec["auto_deactivate"] = ad
    data[node] = rec
    return rec


def set_ha_entity_id(
    data: dict[str, dict[str, Any]],
    node: str,
    entity_id: str,
) -> dict[str, Any]:
    rec = dict(data.get(node) or {})
    rec["ha_entity_id"] = entity_id.strip()
    data[node] = rec
    return rec
