"""Derive the two manifest fields ESPHome is strict about: chipFamily and version.

``chipFamily`` must equal the firmware's ``ESPHOME_VARIANT`` string exactly —
the update component matches on ``build["chipFamily"] == ESPHOME_VARIANT`` and
silently reports "no build" otherwise.

``version`` is compared against the device's ``ESPHOME_PROJECT_VERSION`` when
the config declares a ``project:`` block, and against ``ESPHOME_VERSION``
otherwise. Mirroring that rule here is what makes the update entity behave.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

LOG = logging.getLogger("metadata")

# target_platform (normalised to lowercase alphanumerics) -> ESPHOME_VARIANT
VARIANTS = {
    "esp32": "ESP32",
    "esp32s2": "ESP32-S2",
    "esp32s3": "ESP32-S3",
    "esp32c2": "ESP32-C2",
    "esp32c3": "ESP32-C3",
    "esp32c5": "ESP32-C5",
    "esp32c6": "ESP32-C6",
    "esp32h2": "ESP32-H2",
    "esp32p4": "ESP32-P4",
    "esp8266": "ESP8266",
    "rp2040": "RP2040",
    "rp2350": "RP2350",
}

# esp_image_header_t.chip_id (uint16 LE at offset 12) -> ESPHOME_VARIANT
CHIP_IDS = {
    0: "ESP32",
    2: "ESP32-S2",
    5: "ESP32-C3",
    9: "ESP32-S3",
    12: "ESP32-C2",
    13: "ESP32-C6",
    16: "ESP32-H2",
}

ESP_IMAGE_MAGIC = 0xE9


class _Loader(yaml.SafeLoader):
    """SafeLoader that tolerates ESPHome's custom tags (!secret, !include, !lambda)."""


_Loader.add_multi_constructor("!", lambda loader, suffix, node: None)


def normalise_platform(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def chip_family_from_binary(blob: bytes) -> str | None:
    """Read the variant out of an ESP32 application image header."""
    if len(blob) < 14 or blob[0] != ESP_IMAGE_MAGIC:
        return None
    chip_id = int.from_bytes(blob[12:14], "little")
    return CHIP_IDS.get(chip_id)


def chip_family(target_platform: str, blob: bytes | None = None) -> tuple[str | None, str]:
    """Return ``(chipFamily, how_it_was_determined)``."""
    mapped = VARIANTS.get(normalise_platform(target_platform))

    # Only ESP32 images carry the extended header. An ESP8266 image opens with
    # the same 0xE9 magic but has segment data where chip_id would be, so
    # sniffing one yields a confident-looking lie — don't ask.
    sniffable = mapped is None or mapped.startswith("ESP32")
    sniffed = chip_family_from_binary(blob) if blob and sniffable else None

    if mapped and sniffed and mapped != sniffed:
        LOG.warning(
            "chipFamily mismatch: dashboard says %s, image header says %s — trusting the header",
            mapped,
            sniffed,
        )
        return sniffed, "image header (dashboard disagreed)"
    if sniffed:
        return sniffed, "image header"
    if mapped:
        return mapped, "dashboard target_platform"
    return None, "unknown"


def _substitute(value: str, substitutions: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1) or match.group(2)
        return str(substitutions.get(key, match.group(0)))

    return re.sub(r"\$\{([^}]+)\}|\$([a-zA-Z_]\w*)", replace, value)


def read_config(config_dir: Path, configuration: str) -> dict[str, Any]:
    """Best-effort parse of a device YAML. Returns {} when it cannot be read."""
    path = config_dir / configuration
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.load(handle, Loader=_Loader)
    except (OSError, yaml.YAMLError) as err:
        LOG.debug("Could not parse %s: %s", path, err)
        return {}
    return data if isinstance(data, dict) else {}


def project_version(config: dict[str, Any]) -> str | None:
    """Return ``project.version`` — the value the device reports as its current version."""
    project = config.get("esphome", {}).get("project") if isinstance(config.get("esphome"), dict) else None
    if not isinstance(project, dict):
        return None
    version = project.get("version")
    if version is None:
        return None
    substitutions = config.get("substitutions") or {}
    return _substitute(str(version), substitutions if isinstance(substitutions, dict) else {})
