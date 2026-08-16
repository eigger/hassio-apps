"""Publish firmware into Home Assistant's /local static path.

Layout under ``<config>/www/<publish_dir>/``:

    livingroom.ota.bin        the firmware, overwritten in place
    livingroom.ota.bin.md5    hex digest, for ota.http_request.flash's md5_url
    livingroom.json           ESP-Web-Tools manifest, for update.http_request

The manifest's ``ota.path`` carries a ``?v=<md5 prefix>`` cache buster. Home
Assistant stamps 31-day cache headers on everything under /local, so a proxy
in front of it (a Cloudflare tunnel, say) would otherwise keep serving a stale
``.bin`` — that extension is cached by default, the ``.json`` is not.

Binaries are written to a temp file and renamed into place. On Linux a rename
swaps the directory entry while any in-flight download keeps reading the old
inode, so republishing mid-download cannot corrupt a device's update.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG = logging.getLogger("publisher")


class Publisher:
    def __init__(self, www_root: Path, publish_dir: str, storage_dir: Path | None = None) -> None:
        self.www_root = www_root
        self.dir = www_root / publish_dir
        self.publish_dir = publish_dir
        self.storage_dir = storage_dir or Path("/data/firmware")

    def ensure_dirs(self) -> bool:
        """Create the output and storage directories. Returns True if Home Assistant needs a restart."""
        needs_restart = not self.www_root.is_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Fallback if /data is not writable (e.g. running in local test environment)
            self.storage_dir = self.www_root.parent / "esphome" / "ota_server" / ".firmware"
            self.storage_dir.mkdir(parents=True, exist_ok=True)
        if needs_restart:
            LOG.warning(
                "Created %s — Home Assistant must be restarted once before /local works",
                self.www_root,
            )
        return needs_restart

    def publish(
        self,
        node: str,
        blob: bytes,
        chip_family: str,
        version: str,
        title: str,
        summary: str = "",
        token: str = "",
        previous_token: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_dirs()
        digest = hashlib.md5(blob).hexdigest()  # noqa: S324 - ESPHome's OTA checksum is MD5
        slug = f"{node}_{token}" if token else node
        bin_name = f"{slug}.ota.bin"

        # 1. Save main (token-slugged) binary in private add-on storage and /local
        self._atomic_write(self.storage_dir / bin_name, blob)
        self._atomic_write(self.storage_dir / f"{bin_name}.md5", digest.encode("ascii"))
        self._atomic_write(self.dir / bin_name, blob)
        self._atomic_write(self.dir / f"{bin_name}.md5", digest.encode("ascii"))

        manifest = {
            "name": title or node,
            "version": version,
            "builds": [
                {
                    "chipFamily": chip_family,
                    # Relative on purpose: ESPHome resolves it against the
                    # manifest's own URL, so the same files work over the LAN
                    # and through a remote tunnel with no rewriting.
                    "ota": {
                        "md5": digest,
                        "path": f"{bin_name}?v={digest[:8]}",
                        "summary": summary or "Built by ESPHome OTA Publisher",
                    },
                }
            ],
        }
        manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode("utf-8")
        self._atomic_write(self.dir / f"{slug}.json", manifest_bytes)
        self._atomic_write(self.storage_dir / f"{slug}.json", manifest_bytes)

        # 2. If previous_token is set, also publish bridge paths for existing devices (1-cycle transition)
        has_bridge = previous_token is not None
        prev_slug = ""
        if has_bridge:
            prev_slug = f"{node}_{previous_token}" if previous_token else node
            prev_bin = f"{prev_slug}.ota.bin"
            self._atomic_write(self.dir / prev_bin, blob)
            self._atomic_write(self.dir / f"{prev_bin}.md5", digest.encode("ascii"))
            self._atomic_write(self.storage_dir / prev_bin, blob)
            self._atomic_write(self.storage_dir / f"{prev_bin}.md5", digest.encode("ascii"))

            prev_manifest = {
                "name": title or node,
                "version": version,
                "builds": [
                    {
                        "chipFamily": chip_family,
                        "ota": {
                            "md5": digest,
                            "path": f"{prev_bin}?v={digest[:8]}",
                            "summary": summary or "Built by ESPHome OTA Publisher",
                        },
                    }
                ],
            }
            prev_bytes = json.dumps(prev_manifest, separators=(",", ":")).encode("utf-8")
            self._atomic_write(self.dir / f"{prev_slug}.json", prev_bytes)
            self._atomic_write(self.storage_dir / f"{prev_slug}.json", prev_bytes)

        record = {
            "node": node,
            "token": token,
            "slug": slug,
            "previous_token": previous_token,
            "md5": digest,
            "version": version,
            "chip_family": chip_family,
            "size": len(blob),
            "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "has_bin": True,
            "has_stashed_bin": True,
        }
        LOG.info(
            "Published %s (slug=%s, bridge=%s, %s, %s bytes, %s)",
            node,
            slug,
            prev_slug if has_bridge else None,
            chip_family,
            len(blob),
            digest[:8],
        )
        return record

    def deactivate_binary(self, node: str, token: str = "", previous_token: str | None = None) -> bool:
        """Deactivate (hide) the binary from /local, keeping it in add-on storage and keeping .json manifest in /local."""
        self.ensure_dirs()
        slug = f"{node}_{token}" if token else node
        targets = [slug]
        if previous_token is not None:
            targets.append(f"{node}_{previous_token}" if previous_token else node)

        # Ensure binaries and manifests are in storage before unlinking from /local
        for s in targets:
            name = f"{s}.ota.bin"
            bin_src = self.dir / name
            bin_dst = self.storage_dir / name
            if bin_src.is_file() and not bin_dst.is_file():
                self._atomic_write(bin_dst, bin_src.read_bytes())
                md5_src = self.dir / f"{name}.md5"
                if md5_src.is_file():
                    self._atomic_write(self.storage_dir / f"{name}.md5", md5_src.read_bytes())

            json_src = self.dir / f"{s}.json"
            if json_src.is_file() and not (self.storage_dir / f"{s}.json").is_file():
                self._atomic_write(self.storage_dir / f"{s}.json", json_src.read_bytes())

            (self.dir / f"{s}.ota.bin").unlink(missing_ok=True)
            (self.dir / f"{s}.ota.bin.md5").unlink(missing_ok=True)

        LOG.info("Deactivated firmware binary for %s (slug=%s, targets=%s, removed from /local)", node, slug, targets)
        return True

    def activate_binary(self, node: str, token: str = "", previous_token: str | None = None) -> bool:
        """Activate (deploy) the stashed binary from add-on storage back to /local."""
        self.ensure_dirs()
        slug = f"{node}_{token}" if token else node
        targets = [slug]
        if previous_token is not None:
            targets.append(f"{node}_{previous_token}" if previous_token else node)

        bin_stashed = self.storage_dir / f"{slug}.ota.bin"
        if not bin_stashed.is_file():
            bin_stashed = self.storage_dir / f"{node}.ota.bin"
        if not bin_stashed.is_file():
            raise FileNotFoundError(f"No stashed firmware binary found for {node}.")

        blob = bin_stashed.read_bytes()
        md5_stashed = self.storage_dir / f"{slug}.ota.bin.md5"
        if not md5_stashed.is_file():
            md5_stashed = self.storage_dir / f"{node}.ota.bin.md5"
        md5_bytes = md5_stashed.read_bytes() if md5_stashed.is_file() else hashlib.md5(blob).hexdigest().encode("ascii")

        for s in targets:
            self._atomic_write(self.dir / f"{s}.ota.bin", blob)
            self._atomic_write(self.dir / f"{s}.ota.bin.md5", md5_bytes)
            json_stashed = self.storage_dir / f"{s}.json"
            if json_stashed.is_file() and not (self.dir / f"{s}.json").is_file():
                self._atomic_write(self.dir / f"{s}.json", json_stashed.read_bytes())

        LOG.info("Activated firmware binary for %s (slug=%s, targets=%s, deployed to /local)", node, slug, targets)
        return True

    def delete_binary(self, node: str, token: str = "") -> None:
        """Delete only the .ota.bin and .ota.bin.md5 from /local (alias for deactivate)."""
        self.deactivate_binary(node, token=token)

    def published(self, node: str, token: str = "") -> dict[str, Any] | None:
        slug = f"{node}_{token}" if token else node
        manifest_path = self.dir / f"{slug}.json"
        if not manifest_path.is_file():
            manifest_path = self.storage_dir / f"{slug}.json"
        if not manifest_path.is_file():
            # Fallback to legacy filename
            manifest_path = self.dir / f"{node}.json"
            if not manifest_path.is_file():
                manifest_path = self.storage_dir / f"{node}.json"
                if not manifest_path.is_file():
                    return None

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        build = (manifest.get("builds") or [{}])[0]
        ota = build.get("ota") or {}

        bin_local = self.dir / f"{slug}.ota.bin"
        if not bin_local.is_file():
            bin_local = self.dir / f"{node}.ota.bin"

        bin_stashed = self.storage_dir / f"{slug}.ota.bin"
        if not bin_stashed.is_file():
            bin_stashed = self.storage_dir / f"{node}.ota.bin"

        has_bin = bin_local.is_file()
        has_stashed_bin = bin_stashed.is_file()
        bin_size = (
            bin_local.stat().st_size
            if has_bin
            else (bin_stashed.stat().st_size if has_stashed_bin else 0)
        )
        return {
            "node": node,
            "token": token,
            "slug": slug,
            "title": manifest.get("name", node),
            "version": manifest.get("version", ""),
            "summary": ota.get("summary", ""),
            "md5": ota.get("md5", ""),
            "chip_family": build.get("chipFamily", ""),
            "has_bin": has_bin,
            "has_stashed_bin": has_stashed_bin,
            "bin_size": bin_size,
            "published_at": datetime.fromtimestamp(
                manifest_path.stat().st_mtime, tz=timezone.utc
            ).isoformat(timespec="seconds"),
        }

    def cleanup_old_token(self, node: str, old_token: str) -> None:
        """Remove all files associated with a previous secret token."""
        if not old_token:
            return
        self.ensure_dirs()
        old_slug = f"{node}_{old_token}"
        for d in (self.dir, self.storage_dir):
            if d.is_dir():
                for name in (f"{old_slug}.json", f"{old_slug}.ota.bin", f"{old_slug}.ota.bin.md5"):
                    (d / name).unlink(missing_ok=True)
        LOG.info("Cleaned up previous token files for %s (old slug: %s)", node, old_slug)

    def cleanup_bridge(self, node: str, previous_token: str | None) -> None:
        """Remove bridge files (either old token or un-tokenized legacy) once a device has upgraded."""
        if previous_token is None:
            return
        self.ensure_dirs()
        prev_slug = f"{node}_{previous_token}" if previous_token else node
        for d in (self.dir, self.storage_dir):
            if d.is_dir():
                for name in (f"{prev_slug}.json", f"{prev_slug}.ota.bin", f"{prev_slug}.ota.bin.md5"):
                    (d / name).unlink(missing_ok=True)
        LOG.info("Cleaned up migration bridge files for %s (bridge slug: %s)", node, prev_slug)

    def cleanup_legacy_bridge(self, node: str) -> None:
        """Backward compatibility alias for cleanup_bridge(node, '')."""
        self.cleanup_bridge(node, "")

    def list_published(self, registered: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
        """Every published node's manifest, read from disk (both /local and storage)."""
        result = {}
        # 1. Check for all registered devices with their assigned tokens
        if registered:
            for node, rec in registered.items():
                token = rec.get("token") or ""
                record = self.published(node, token=token)
                if record:
                    result[node] = record

        # 2. Check disk for any other published manifests (legacy, bridge, or unregistered)
        token_pattern = re.compile(r"^(.+)_([0-9a-fA-F]{32})$")
        for d in (self.dir, self.storage_dir):
            if d.is_dir():
                for manifest_path in list(d.glob("*.json")):
                    stem = manifest_path.stem
                    m = token_pattern.match(stem)
                    if m:
                        base_node, file_token = m.group(1), m.group(2)
                        if registered and base_node in registered:
                            current_tok = (registered[base_node] or {}).get("token") or ""
                            prev_tok = (registered[base_node] or {}).get("previous_token")
                            if file_token not in (current_tok, prev_tok):
                                # Orphaned token file from a previous version — clean it up
                                self.cleanup_old_token(base_node, file_token)
                                continue
                        if base_node not in result:
                            record = self.published(base_node, token=file_token)
                            if record:
                                result[base_node] = record
                    else:
                        # Legacy un-tokenized manifest
                        if registered and stem in registered:
                            prev_tok = (registered[stem] or {}).get("previous_token")
                            # If device already has a token and no legacy bridge active, purge stale legacy file
                            if (registered[stem] or {}).get("token") and prev_tok != "":
                                self.cleanup_bridge(stem, "")
                                continue
                        if stem not in result:
                            record = self.published(stem)
                            if record:
                                result[stem] = record
        return result

    def unpublish(self, node: str, token: str = "") -> None:
        """Delete all published files from /local and add-on storage for both slug and legacy."""
        self.ensure_dirs()
        slug = f"{node}_{token}" if token else node
        for d in (self.dir, self.storage_dir):
            if not d.is_dir():
                continue
            for s in (slug, node):
                for name in (f"{s}.json", f"{s}.ota.bin", f"{s}.ota.bin.md5"):
                    (d / name).unlink(missing_ok=True)
            # Glob cleanup for any other tokenized files matching {node}_<token>
            for f in list(d.glob(f"{node}_*.json")) + list(d.glob(f"{node}_*.ota.bin")) + list(d.glob(f"{node}_*.ota.bin.md5")):
                f.unlink(missing_ok=True)

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(payload)
        os.replace(tmp, path)

