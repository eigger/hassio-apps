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
import os
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


def chip_family_from_platform(target_platform: str) -> str | None:
    """chipFamily from a YAML/dashboard platform key, with no image to sniff.

    ``esp32:`` is every ESP32 variant — mapping that to classic ``ESP32``
    locks the manual form until upload. Leave it unknown; ESP8266/RP2040
    have no header chip_id, so those mappings are kept.
    """
    family, _ = chip_family(target_platform)
    return None if family == "ESP32" else family


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


def read_yaml_file(path: Path) -> dict[str, Any] | None:
    """Best-effort parse of one YAML file. Returns None when it cannot be read."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.load(handle, Loader=_Loader)
    except (OSError, yaml.YAMLError) as err:
        LOG.debug("Could not parse %s: %s", path, err)
        return None
    if data is None:
        return {}
    return data if isinstance(data, dict) else {}


def read_config(config_dir: Path, configuration: str) -> dict[str, Any] | None:
    """Best-effort parse of a device YAML. Returns None when it cannot be read."""
    return read_yaml_file(config_dir / configuration)


def is_yaml_unreadable(config_dir: Path, node: str) -> bool:
    """True when the device YAML exists on disk but cannot be parsed."""
    filename = find_configuration(config_dir, node)
    if not filename:
        return False
    return read_config(config_dir, filename) is None


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
    cache: dict[Path, dict[str, Any] | None],
) -> tuple[dict[str, Any], Path] | None:
    path = _include_path(config_dir, origin, rel)
    if path is None or path in seen:
        return None
    seen.add(path)
    if path not in cache:
        cache[path] = read_yaml_file(path)
    data = cache[path]
    if data is None:
        return None
    return data, path


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
    data = read_yaml_file(config_dir / _WRAPPER_DIR / f"{node}.yaml")
    return project_version(data) if data is not None else None


def own_project_version(
    config_dir: Path,
    node: str,
    cache: dict[Path, dict[str, Any] | None] | None = None,
) -> str | None:
    """Device YAML's self-declared esphome.project.version, ignoring generated wrappers.

    Returns None when the add-on owns the version (auto mode).
    """
    filename = find_configuration(config_dir, node)
    if not filename:
        return None
    config = read_config(config_dir, filename)
    if config is None:
        return None
    origin = config_dir / filename
    merged, _ = merge_config(
        config_dir, config, origin, skip_wrapper_node=node, cache=cache
    )
    return project_version(merged)


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
    compile that wrapper, so they report ``ESPHOME_VERSION``. In auto mode,
    wrappers carry ``esphome.project`` so included devices report that; in
    manual mode (device declares its own ``project:``), the wrapper omits it
    and the device YAML's own declaration is used.
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
        if config is None:
            continue
        merged, uses_wrapper = merge_config(
            config_dir, config, path, skip_wrapper_node=node, cache=cache
        )
        esphome = merged.get("esphome")
        if not isinstance(esphome, dict) or not esphome:
            continue

        publishable = bool(NODE_RE.match(node))
        platform = target_platform_from_config(merged)
        family = chip_family_from_platform(platform) if platform else None
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


def is_injected(config_dir: Path, node: str) -> bool:
    """Check if the device YAML file directly includes this add-on's wrapper."""
    filename = find_configuration(config_dir, node)
    if not filename:
        return False
    path = config_dir / filename
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return False
    pattern = rf"!include\s+ota_server/devices/{re.escape(node)}(\.update|\.button)?\.ya?ml"
    return bool(re.search(pattern, content))


def inject_device_wrapper(config_dir: Path, node: str) -> tuple[bool, str]:
    """Inject `packages: ota: !include ota_server/devices/{node}.yaml` into the device YAML."""
    filename = find_configuration(config_dir, node)
    if not filename:
        return False, f"Configuration file not found for {node}"
    path = config_dir / filename
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as err:
        return False, f"Could not read {filename}: {err}"

    include_stmt = f"ota: !include ota_server/devices/{node}.yaml"
    target_pattern = rf"!include\s+ota_server/devices/{re.escape(node)}(\.update|\.button)?\.ya?ml"

    if re.search(target_pattern, content):
        return True, f"OTA package is already applied to {filename}"

    lines = content.splitlines(keepends=True)
    pkg_line_idx = -1
    pkg_indent = ""

    for i, line in enumerate(lines):
        match = re.match(r"^(\s*)packages:\s*(#.*)?$", line)
        if match and len(match.group(1)) == 0:  # Top-level packages
            pkg_line_idx = i
            pkg_indent = match.group(1)
            break
        # Guard against incompatible inline packages definitions (e.g. packages: !include ...)
        if re.match(r"^packages:\s*\S+", line):
            return False, f"Cannot inject into {filename}: inline 'packages:' format is not supported. Please use YAML snippet manually."

    if pkg_line_idx != -1:
        # Find if an `ota:` key already exists under `packages:`
        ota_idx = -1
        next_top_idx = len(lines)
        for i in range(pkg_line_idx + 1, len(lines)):
            l = lines[i]
            if not l.strip() or l.strip().startswith("#"):
                continue
            # If line is not indented, it's the next top-level key
            if not l.startswith(" ") and not l.startswith("\t"):
                next_top_idx = i
                break
            if re.match(r"^\s+ota:\s*", l):
                ota_idx = i
                break

        if ota_idx != -1:
            # Replace existing ota line
            indent = re.match(r"^(\s*)", lines[ota_idx]).group(1) or "  "
            lines[ota_idx] = f"{indent}{include_stmt}\n"
        else:
            # Insert right after `packages:`
            lines.insert(pkg_line_idx + 1, f"  {include_stmt}\n")
        new_content = "".join(lines)
    else:
        # No top-level packages block exists; append at end
        addition = f"\npackages:\n  {include_stmt}\n"
        if content and not content.endswith("\n"):
            addition = "\n" + addition
        new_content = content + addition

    # Create safety backup on disk if not already existing, and atomic write
    try:
        bak_path = path.with_suffix(path.suffix + ".bak")
        if not bak_path.exists():
            bak_path.write_text(content, encoding="utf-8")
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(new_content, encoding="utf-8")
        os.replace(tmp_path, path)
    except OSError as err:
        return False, f"Failed to write {filename}: {err}"

    return True, f"Successfully injected OTA package into {filename}"


def eject_device_wrapper(config_dir: Path, node: str) -> tuple[bool, str]:
    """Remove the OTA package include from the device YAML."""
    filename = find_configuration(config_dir, node)
    if not filename:
        return False, f"Configuration file not found for {node}"
    path = config_dir / filename
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as err:
        return False, f"Could not read {filename}: {err}"

    target_pattern = rf"^\s*(ota:\s*)?!include\s+ota_server/devices/{re.escape(node)}(\.update|\.button)?\.ya?ml\s*$"
    if not re.search(rf"!include\s+ota_server/devices/{re.escape(node)}", content):
        return True, f"OTA package was not found in {filename}"

    lines = content.splitlines(keepends=True)
    new_lines: list[str] = []
    removed_any = False

    for line in lines:
        if re.search(target_pattern, line.strip()):
            removed_any = True
            continue
        new_lines.append(line)

    # Clean up empty `packages:` section if nothing left under it
    cleaned_lines: list[str] = []
    i = 0
    while i < len(new_lines):
        line = new_lines[i]
        if re.match(r"^packages:\s*$", line.strip()):
            # Check if there are indented lines following it
            has_children = False
            j = i + 1
            while j < len(new_lines):
                next_l = new_lines[j]
                if not next_l.strip():
                    j += 1
                    continue
                if next_l.startswith(" ") or next_l.startswith("\t"):
                    has_children = True
                break
            if not has_children:
                # Skip the packages: line and any immediate blank line
                i = j
                continue
        cleaned_lines.append(line)
        i += 1

    new_content = "".join(cleaned_lines)

    try:
        bak_path = path.with_suffix(path.suffix + ".bak")
        if not bak_path.exists():
            bak_path.write_text(content, encoding="utf-8")
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(new_content, encoding="utf-8")
        os.replace(tmp_path, path)
    except OSError as err:
        return False, f"Failed to write {filename}: {err}"

    return True, f"Successfully removed OTA package from {filename}"


ESP_APP_DESC_MAGIC = 0xABCD5432

# esp_app_desc_t layout (relative to struct start at blob offset 0x20 — this
# add-on only ever sees OTA/app images, i.e. what ``ota.download_ota()`` and
# the manual-upload form's app-image check hand us, never a factory image):
#   +0x00  magic        uint32
#   +0x04  secure_ver   uint32
#   +0x08  reserv1[2]   uint32×2
#   +0x10  version[32]  char  ← ESPHome/ESP-IDF framework version, e.g. "2026.7.4"
#   +0x30  project_name[32] char  ← the compiled node name (CMake PROJECT_NAME)
#   +0x50  time[16]     char  ← GCC __TIME__  "HH:MM:SS"
#   +0x60  date[16]     char  ← GCC __DATE__  "Mmm DD YYYY"
#   +0x70  idf_ver[32]  char
#   +0x90  app_elf_sha256[32] bytes


# ESPHome's boot-log banner, compiled in only when ``project:`` is set in the
# device YAML *and* the logger isn't fully disabled:
#   ESP_LOGI(TAG, "Project %s version %s", ESPHOME_PROJECT_NAME, ESPHOME_PROJECT_VERSION);
# Both operands are string constants, so the format string and its arguments
# are all concatenated by the compiler into one ``.rodata`` literal — no
# ``%s`` survives to runtime. This is the same value the device itself
# reports as ESPHOME_PROJECT_VERSION, which is what update.http_request
# string-compares against, so it is the authoritative "what will the device
# say it's running" answer — the esp_app_desc_t.version field above is only
# the ESPHome/ESP-IDF *framework* version, not the project version.
_RE_PROJECT_VERSION = re.compile(
    rb"Project ([\x20-\x7e]{1,63}?) version ([\x20-\x7e]{1,63})\x00"
)

# App.pre_setup()'s compiled-in build timestamp: ``__DATE__ __TIME__`` plus a
# UTC offset, formatted by ESPHome as "YYYY-MM-DD HH:MM:SS +ZZZZ". Present in
# every ESPHome image regardless of logger level or project: block, and
# unlike esp_app_desc_t.time/date it survives ESP-IDF's reproducible-build
# option (which zeroes those two struct fields).
_RE_LITERAL_BUILD_TIME = re.compile(
    rb"(20\d\d-[01]\d-[0-3]\d[ T][0-2]\d:[0-5]\d:[0-5]\d(?: ?[+-]\d{4})?)\x00"
)

_MONTH_MAP = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def _parse_build_datetime(date_str: str, time_str: str) -> str | None:
    """Convert GCC __DATE__/__TIME__ strings to an ISO-8601 UTC-unaware string.

    GCC encodes the local build time with no timezone info, so we emit the
    raw value as-is rather than pretending it is UTC.  The returned string
    is ``"YYYY-MM-DDTHH:MM:SS"`` (no timezone suffix), which the frontend
    can display verbatim.
    """
    try:
        parts = date_str.split()
        if len(parts) != 3:
            return None
        month = _MONTH_MAP.get(parts[0])
        day = int(parts[1])
        year = int(parts[2])
        if not month:
            return None
        h, m, s = (int(x) for x in time_str.split(":"))
        return f"{year:04d}-{month:02d}-{day:02d}T{h:02d}:{m:02d}:{s:02d}"
    except Exception:
        return None


def _find_literal_build_time(blob: bytes) -> str | None:
    """Scan for ESPHome's compiled-in "YYYY-MM-DD HH:MM:SS +ZZZZ" literal."""
    match = _RE_LITERAL_BUILD_TIME.search(blob)
    if not match:
        return None
    return match.group(1).decode("ascii", errors="ignore")


def _find_project_version(blob: bytes) -> tuple[str, str] | None:
    """Scan for the "Project <name> version <version>" boot-log literal.

    Returns ``(project_name, project_version)``, or None when the logger
    stripped this string out at compile time (e.g. ``logger.level: NONE``).
    """
    match = _RE_PROJECT_VERSION.search(blob)
    if not match:
        return None
    name = match.group(1).decode("utf-8", errors="ignore").strip()
    version = match.group(2).decode("utf-8", errors="ignore").strip()
    if not name or not version:
        return None
    return name, version


def parse_app_descriptor(blob: bytes) -> dict[str, str]:
    """Parse esp_app_desc_t at offset 0x20, plus ESPHome's own boot literals.

    ``build_time`` prefers the struct's __DATE__/__TIME__ fields when a
    non-reproducible build actually populated them, falling back to
    ESPHome's compiled-in timestamp literal (which survives reproducible
    builds — the case for every stock ESPHome release). ``project_version``/
    ``project_literal_name`` come from the "Project X version Y" boot-log
    literal, which is the value the device actually reports at runtime and
    what update.http_request string-compares against — distinct from
    ``version`` (ESPHome/ESP-IDF framework version) and the struct's
    ``project_name`` (compiled node name, not ``esphome.project.name``).
    """
    if len(blob) < 0x20 + 160:
        return {}
    magic = int.from_bytes(blob[0x20:0x24], "little")
    if magic != ESP_APP_DESC_MAGIC:
        return {}
    try:
        ver_bytes = blob[0x30:0x50].split(b"\x00")[0]
        version = ver_bytes.decode("utf-8", errors="ignore").strip()
        proj_bytes = blob[0x50:0x70].split(b"\x00")[0]
        project = proj_bytes.decode("utf-8", errors="ignore").strip()
        time_bytes = blob[0x70:0x80].split(b"\x00")[0]
        build_time_str = time_bytes.decode("utf-8", errors="ignore").strip()
        date_bytes = blob[0x80:0x90].split(b"\x00")[0]
        build_date_str = date_bytes.decode("utf-8", errors="ignore").strip()
        idf_bytes = blob[0x90:0xB0].split(b"\x00")[0]
        idf_ver = idf_bytes.decode("utf-8", errors="ignore").strip()
        result: dict[str, str] = {
            "version": version,
            "project_name": project,
            "idf_version": idf_ver,
        }
        build_dt = _parse_build_datetime(build_date_str, build_time_str) or _find_literal_build_time(blob)
        if build_dt:
            result["build_time"] = build_dt

        literal = _find_project_version(blob)
        if literal:
            result["project_literal_name"], result["project_version"] = literal
        return result
    except Exception:
        return {}


def validate_binary(
    blob: bytes,
    chip_family_or_platform: str = "",
    max_size: int = 32 * 1024 * 1024,
) -> tuple[bool, str, dict[str, Any]]:
    """Validate uploaded binary before publishing."""
    if not blob:
        return False, "Binary file is empty (0 bytes).", {}
    if len(blob) < 4096:
        return False, f"File is too small to be a valid firmware ({len(blob)} bytes).", {}
    if len(blob) > max_size:
        return False, f"File exceeds maximum allowed firmware size ({len(blob)} bytes > {max_size // (1024 * 1024)}MB).", {}

    if blob[:4] == b"UF2\n":
        return False, "Detected UF2 file. ESPHome OTA requires an application .bin file.", {}
    if blob[:4] == b"\x7fELF":
        return False, "Detected ELF executable. Please upload the compiled .ota.bin file.", {}

    target = (chip_family_or_platform or "").strip().lower()
    is_esp = not target or target.startswith("esp") or "esp32" in target or "esp8266" in target

    chip_family = None
    app_desc = {}

    if blob[0] == ESP_IMAGE_MAGIC:
        chip_family = chip_family_from_binary(blob)
        if chip_family and "ESP32" in chip_family:
            app_desc = parse_app_descriptor(blob)
    elif is_esp:
        return False, f"Invalid image magic byte (0x{blob[0]:02X} != 0xE9). Expected ESP binary image.", {}

    info: dict[str, Any] = {
        "size": len(blob),
        "chip_family": chip_family,
        "app_descriptor": app_desc,
    }
    return True, "Valid firmware binary", info



