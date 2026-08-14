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

# Published filenames and device-wrapper stems. Same rule the dashboard uses
# for configuration names (the YAML filename without its extension).
NODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,62}$")

_SKIP_FILENAMES = {"secrets.yaml", "secrets.yml"}
_SKIP_DIRS = {"ota_server", "archive"}
# Top-level YAML keys that mean "this file is a device, not a package".
_PLATFORM_KEYS = (
    "esp32",
    "esp8266",
    "rp2040",
    "rp2350",
    "bk72xx",
    "rtl87xx",
    "ln882x",
    "host",
)


class _Loader(yaml.SafeLoader):
    """SafeLoader that tolerates ESPHome's custom tags (!secret, !include, !lambda)."""


def _unknown_tag(loader: yaml.Loader, suffix: str, node: yaml.Node) -> Any:
    """Keep ``!include`` paths so package-split configs can still be detected."""
    if suffix != "include":
        return None
    if isinstance(node, yaml.ScalarNode):
        return {"__include__": loader.construct_scalar(node)}
    if isinstance(node, yaml.MappingNode):
        mapping = loader.construct_mapping(node, deep=True)
        file = mapping.get("file")
        if file:
            return {"__include__": str(file)}
    return None


_Loader.add_multi_constructor("!", _unknown_tag)


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


def read_yaml_file(path: Path) -> dict[str, Any]:
    """Best-effort parse of one YAML file. Returns {} when it cannot be read."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.load(handle, Loader=_Loader)
    except (OSError, yaml.YAMLError) as err:
        LOG.debug("Could not parse %s: %s", path, err)
        return {}
    return data if isinstance(data, dict) else {}


def read_config(config_dir: Path, configuration: str) -> dict[str, Any]:
    """Best-effort parse of a device YAML. Returns {} when it cannot be read."""
    return read_yaml_file(config_dir / configuration)


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


def _include_rel(value: Any) -> str | None:
    if isinstance(value, dict) and value.get("__include__"):
        return str(value["__include__"])
    return None


def _include_path(config_dir: Path, origin: Path, rel: str) -> Path | None:
    raw = Path(rel)
    for candidate in ((origin.parent / raw), (config_dir / raw)):
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_file():
            return resolved
    return None


def _load_include(
    config_dir: Path,
    rel: str,
    origin: Path,
    seen: set[Path],
    cache: dict[Path, dict[str, Any]],
) -> tuple[dict[str, Any], Path] | None:
    path = _include_path(config_dir, origin, rel)
    if path is None or path in seen:
        return None
    seen.add(path)
    if path not in cache:
        cache[path] = read_yaml_file(path)
    return cache[path], path


def _norm_include(rel: str) -> str:
    return rel.replace("\\", "/").lstrip("./")


def is_device_wrapper_include(rel: str, node: str) -> bool:
    """True when *rel* points at this add-on's per-device wrapper for *node*."""
    path = _norm_include(rel)
    if "/ota_server/devices/" not in f"/{path}":
        return False
    name = path.rsplit("/", 1)[-1]
    for suffix in (".update.yaml", ".button.yaml", ".update.yml", ".button.yml", ".yaml", ".yml"):
        if name.endswith(suffix):
            return name[: -len(suffix)] == node
    return False


def _overlay(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """ESPHome-ish dict merge: *overlay* wins per key; nested dicts merge."""
    out = dict(base)
    for key, value in overlay.items():
        if key == "packages":
            continue
        rel = _include_rel(value)
        if rel:
            continue
        existing = out.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            out[key] = {**existing, **value}
        else:
            out[key] = value
    return out


def merge_config(
    config_dir: Path,
    config: dict[str, Any],
    origin: Path,
    seen: set[Path] | None = None,
    depth: int = 0,
    skip_wrapper_node: str | None = None,
    cache: dict[Path, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Follow ``!include`` packages and merge top-level keys. This file wins.

    Wrapper includes for *skip_wrapper_node* are skipped so a generated
    ``esphome.project`` is not mistaken for one the device YAML declared.
    Returns ``(merged, uses_wrapper)``.
    """
    if depth > 8 or not isinstance(config, dict):
        return (config if isinstance(config, dict) else {}), False
    seen = seen if seen is not None else set()
    cache = cache if cache is not None else {}
    merged: dict[str, Any] = {}
    uses_wrapper = False

    def apply_included(rel: str, from_origin: Path) -> None:
        nonlocal merged, uses_wrapper
        if skip_wrapper_node and is_device_wrapper_include(rel, skip_wrapper_node):
            uses_wrapper = True
            return
        loaded = _load_include(config_dir, rel, from_origin, seen, cache)
        if not loaded:
            return
        data, path = loaded
        nested, nested_uses = merge_config(
            config_dir,
            data,
            path,
            seen,
            depth + 1,
            skip_wrapper_node=skip_wrapper_node,
            cache=cache,
        )
        uses_wrapper = uses_wrapper or nested_uses
        merged = _overlay(merged, nested)

    packages = config.get("packages")
    package_rel = _include_rel(packages)
    origin_for_pkgs = origin
    if package_rel:
        if skip_wrapper_node and is_device_wrapper_include(package_rel, skip_wrapper_node):
            uses_wrapper = True
            packages = {}
        else:
            loaded = _load_include(config_dir, package_rel, origin, seen, cache)
            if loaded:
                data, path = loaded
                packages = data
                origin_for_pkgs = path
            else:
                packages = {}

    items: list[Any]
    if isinstance(packages, dict):
        items = list(packages.values())
    elif isinstance(packages, list):
        items = list(packages)
    else:
        items = []

    for item in items:
        rel = _include_rel(item)
        if rel:
            apply_included(rel, origin_for_pkgs)
        elif isinstance(item, dict):
            nested, nested_uses = merge_config(
                config_dir,
                item,
                origin_for_pkgs,
                seen,
                depth + 1,
                skip_wrapper_node=skip_wrapper_node,
                cache=cache,
            )
            uses_wrapper = uses_wrapper or nested_uses
            merged = _overlay(merged, nested)

    for key, value in config.items():
        if key == "packages":
            continue
        rel = _include_rel(value)
        if rel:
            if skip_wrapper_node and is_device_wrapper_include(rel, skip_wrapper_node):
                uses_wrapper = True
                continue
            loaded = _load_include(config_dir, rel, origin, seen, cache)
            if not loaded:
                continue
            data, path = loaded
            nested, nested_uses = merge_config(
                config_dir,
                data,
                path,
                seen,
                depth + 1,
                skip_wrapper_node=skip_wrapper_node,
                cache=cache,
            )
            uses_wrapper = uses_wrapper or nested_uses
            existing = merged.get(key)
            if isinstance(existing, dict) and isinstance(nested, dict):
                merged[key] = {**existing, **nested}
            else:
                merged[key] = nested
            continue
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = {**existing, **value}
        else:
            merged[key] = value
    return merged, uses_wrapper


# Mirrors packages.PACKAGE_DIR/DEVICES_DIR without importing packages (cycle).
_WRAPPER_DIR = Path("ota_server") / "devices"


def wrapper_project_version(config_dir: Path, node: str) -> str | None:
    """Version the generated wrapper injects — what a compiled device actually reports."""
    return project_version(read_yaml_file(config_dir / _WRAPPER_DIR / f"{node}.yaml"))


def effective_project_version(
    config_dir: Path,
    node: str,
    config: dict[str, Any],
    origin: Path | None = None,
    cache: dict[Path, dict[str, Any]] | None = None,
) -> str | None:
    """Version the compiled firmware reports: device ``project:``, else the wrapper if used.

    A wrapper file on disk is not enough — legacy configs that still use
    ``substitutions.ota_device`` + ``!include ota_server/ota.yaml`` never
    compile that wrapper, so they report ``ESPHOME_VERSION``. A wrapper
    with no ``project:`` block (device YAML has none either) is the same.
    """
    origin = origin or config_dir / f"{node}.yaml"
    merged, uses_wrapper = merge_config(
        config_dir, config, origin, skip_wrapper_node=node, cache=cache
    )
    own = project_version(merged)
    if own:
        return own
    if uses_wrapper:
        return wrapper_project_version(config_dir, node)
    return None


def node_from_configuration(configuration: str) -> str:
    """YAML filename without extension — the publish slug."""
    name = Path(configuration).name
    if name.endswith(".yaml"):
        return name[:-5]
    if name.endswith(".yml"):
        return name[:-4]
    return name


def _as_text(value: Any, substitutions: dict[str, Any]) -> str:
    if value is None or isinstance(value, (dict, list)):
        return ""
    return _substitute(str(value), substitutions)


def friendly_name(config: dict[str, Any], fallback: str) -> str:
    esphome = config.get("esphome") if isinstance(config.get("esphome"), dict) else {}
    substitutions = config.get("substitutions") if isinstance(config.get("substitutions"), dict) else {}
    for key in ("friendly_name", "name"):
        text = _as_text(esphome.get(key), substitutions)
        if text:
            return text
    return fallback


def target_platform_from_config(config: dict[str, Any]) -> str:
    for key in _PLATFORM_KEYS:
        if key in config:
            return key
    return ""


def find_configuration(config_dir: Path, node: str) -> str | None:
    """Return the YAML filename for *node* (``.yaml`` preferred over ``.yml``)."""
    for ext in (".yaml", ".yml"):
        path = config_dir / f"{node}{ext}"
        if path.is_file():
            return path.name
    return None


def scan_esphome_dir(config_dir: Path) -> tuple[list[dict[str, Any]], set[str]]:
    """Device YAMLs plus every top-level stem (even unparseable).

    Top-level ``*.yaml`` / ``*.yml`` whose ``esphome:`` block is present
    either in the file or via ``!include`` (package-split configs, including
    ``!include {file: ..., vars: ...}``). Platform keys from those packages
    are merged so chip family is known without the dashboard.
    ``secrets.yaml`` and this add-on's generated ``ota_server/`` tree are
    skipped. The publish slug is the filename stem.
    """
    if not config_dir.is_dir():
        return [], set()

    files: list[Path] = []
    for ext in (".yaml", ".yml"):
        files.extend(sorted(p for p in config_dir.glob(f"*{ext}") if p.is_file()))

    stems: set[str] = set()
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    cache: dict[Path, dict[str, Any]] = {}
    for path in files:
        if path.name.lower() in _SKIP_FILENAMES or path.parent.name in _SKIP_DIRS:
            continue
        node = node_from_configuration(path.name)
        if NODE_RE.match(node):
            stems.add(node)
        if node in seen:
            continue
        seen.add(node)

        config = cache[path] if path in cache else read_yaml_file(path)
        cache[path] = config
        merged, uses_wrapper = merge_config(
            config_dir, config, path, skip_wrapper_node=node, cache=cache
        )
        esphome = merged.get("esphome")
        if not isinstance(esphome, dict) or not esphome:
            continue

        publishable = bool(NODE_RE.match(node))
        platform = target_platform_from_config(merged)
        family, _ = chip_family(platform) if platform else (None, "unknown")
        own_version = project_version(merged)
        firmware_version = own_version or (
            wrapper_project_version(config_dir, node) if uses_wrapper else None
        )
        result.append(
            {
                "node": node,
                "configuration": path.name,
                "friendly_name": friendly_name(merged, node),
                "target_platform": platform,
                "chip_family": family,
                "project_version": firmware_version,
                "own_project_version": own_version,
                "uses_wrapper": uses_wrapper,
                "publishable": publishable,
            }
        )
    result.sort(key=lambda row: row["friendly_name"].lower())
    return result, stems
