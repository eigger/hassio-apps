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

# For the manual-publish form: every chipFamily string ESPHome's update
# component might compare against, sorted for a stable dropdown order.
CHIP_FAMILIES = sorted(set(VARIANTS.values()))

# esp_image_header_t.chip_id (uint16 LE at offset 12) -> ESPHOME_VARIANT.
# Values come from esp_chip_id_t (ESP-IDF esp_app_format.h). Keep this in sync
# with VARIANTS: a chip ESPHome can build for but that is missing here used to
# fall back to the dashboard's target_platform, which publishes a wrong-but-
# plausible "ESP32" — see chip_family() below.
CHIP_IDS = {
    0x00: "ESP32",
    0x02: "ESP32-S2",
    0x05: "ESP32-C3",
    0x09: "ESP32-S3",
    0x0C: "ESP32-C2",
    0x0D: "ESP32-C6",
    0x10: "ESP32-H2",
    0x12: "ESP32-P4",
    0x17: "ESP32-C5",
}

ESP_IMAGE_MAGIC = 0xE9
ESP_IMAGE_HEADER_LEN = 24  # sizeof(esp_image_header_t)


class _Loader(yaml.SafeLoader):
    """SafeLoader that tolerates ESPHome's custom tags (!secret, !include, !lambda)."""


_Loader.add_multi_constructor("!", lambda loader, suffix, node: None)


def normalise_platform(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def chip_id_from_binary(blob: bytes) -> int | None:
    """Read esp_image_header_t.chip_id, or None when this isn't an ESP32 image.

    An ESP8266 image opens with the same 0xE9 magic but carries only an 8-byte
    header followed by segment data, so offset 12 there is payload that reads
    back as a confident-looking lie. Check the fields around chip_id first —
    ``reserved`` is zero and ``hash_appended`` is a bool in every real ESP32
    header, which segment data almost never satisfies.
    """
    if len(blob) < ESP_IMAGE_HEADER_LEN or blob[0] != ESP_IMAGE_MAGIC:
        return None
    if blob[19:23] != b"\x00\x00\x00\x00" or blob[23] > 1:
        return None
    return int.from_bytes(blob[12:14], "little")


def chip_family_from_binary(blob: bytes) -> str | None:
    """Read the variant out of an ESP32 application image header."""
    chip_id = chip_id_from_binary(blob)
    return CHIP_IDS.get(chip_id) if chip_id is not None else None


def chip_family(target_platform: str, blob: bytes | None = None) -> tuple[str | None, str]:
    """Return ``(chipFamily, how_it_was_determined)``."""
    mapped = VARIANTS.get(normalise_platform(target_platform))

    # Only ESP32 images carry the extended header. An ESP8266 image opens with
    # the same 0xE9 magic but has segment data where chip_id would be, so
    # sniffing one yields a confident-looking lie — don't ask.
    sniffable = mapped is None or mapped.startswith("ESP32")
    chip_id = chip_id_from_binary(blob) if blob and sniffable else None
    sniffed = CHIP_IDS.get(chip_id) if chip_id is not None else None

    # An ESP32 image whose chip_id we don't recognise. Falling back to `mapped`
    # is worse than failing: the dashboard reports the *component*
    # (target_platform is "esp32" for every variant), so the fallback can only
    # ever produce "ESP32" — a manifest that no non-classic device will match,
    # and whose only symptom is an update entity stuck on "unknown" in HA.
    if chip_id is not None and sniffed is None:
        LOG.error(
            "Unrecognised esp_image_header chip_id 0x%04x — add it to CHIP_IDS (esp_chip_id_t)",
            chip_id,
        )
        return None, f"unrecognised image header chip_id 0x{chip_id:04x}"

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
