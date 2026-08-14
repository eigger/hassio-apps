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
) -> dict[str, Any]:
    rec = dict(data.get(node) or {})
    rec["version"] = version
    if title:
        rec["title"] = title
    rec.setdefault("registered_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    data[node] = rec
    return rec
